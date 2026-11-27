"""Printed pair mechanics through table commits, session intents and cold reload."""
import pytest
from tests.worker2_support import OWNER, ALLY, FOE, fixture, settle, reload, candidate, turn
from tests.cw2_service_support import seal, add_action

T = 'TAL_DUAL_WIELDING_'
FOCUS = 'resource:core.martial_focus'


def kit(*items):
    return {'starting_kit': {'items': [{'item_id': 'tianxia.mortal.weapon.' + item,
        'name': item, 'quantity': 1} for item in items]}}


def setup(bundles):
    for b, bonus in zip(bundles, [100, -100, 0]):
        b['actor_template']['initiative_bonus'] = bonus
        b['actor_template']['maximum_hp'] = 500
        b['actor_template']['armor_class'] = 0
        seal(b)
    bundles[1]['actor_template']['saving_throws']['DEX'] = -100
    bundles[2]['actor_template']['saving_throws']['DEX'] = 100
    add_action(bundles[0], 'Hold focus', [{'type': 'gain_resource','resource_id':FOCUS,'flat':1,'applies_to':'self'}], target='SELF')
    seal(bundles[1]); seal(bundles[2])


def events(e, kind):
    return [v for v in e.events if v.event_type == kind and v.actor_id == OWNER]


@pytest.mark.parametrize('items,sides', [(('duan_jian','bi_shou'), [4,6]),
                                        (('hu_die_dao',), [6,6]),
                                        (('jian','bi_shou'), [4,8]),
                                        (('duan_jian','bi_shou','jian'), [4,6])])
@pytest.mark.parametrize('mode', ['MANUAL','LOCAL_AUTO'])
def test_cyclone_exact_pair_roll_cost_recipients_half_and_reload(tmp_path, items, sides, mode):
    combat, table, mid = fixture(tmp_path, [T+'CYCLONE_CUT',T+'GREATER_BLADES',T+'DANCING_DISPLAY',T+'DEFENSIVE_WHIRL'],
        owner_kit=kit(*items), foe_position={'x':3,'y':5}, bundle_transform=setup,
        modes={OWNER:mode, ALLY:'MANUAL',FOE:'MANUAL'})
    e = reload(tmp_path, mid); hp = {aid:a.current_hp for aid,a in e.state.actors.items()}
    assert not e.action_catalog[candidate(combat,mid,'Cyclone Cut').source_definition_id].parameters['typed']['riders']
    cid = candidate(combat,mid,'Cyclone Cut').candidate_id
    if mode == 'MANUAL':
        settle(table, mid, cid)
    else:
        # Record a chosen primary ability; the real controller resolves all reaction/recipient choices.
        from combat.gate4_adapters import ManualControllerAdapter
        real = combat.controller
        class Controller:
            def choose_primary_action(self, context):
                return ManualControllerAdapter(lambda _: (cid, ())).choose_primary_action(context)
            def __getattr__(self, name):
                return getattr(real, name)
        combat.controller = Controller()
        try:
            settle(table, mid, cid, auto=True)
        finally:
            combat.controller = real
    e = reload(tmp_path,mid)
    rolls = events(e,'DAMAGE_ROLLED')
    assert sorted(int(v.payload['expression'].split('d')[1].split('+')[0]) for v in rolls) == sides
    assert all(v.payload['modifier'] == 0 and len(v.payload['dice']) == 1 for v in rolls)
    total = sum(v.payload['total'] for v in rolls)
    assert hp[ALLY]-e.state.actors[ALLY].current_hp == total
    assert hp[FOE]-e.state.actors[FOE].current_hp == total//2
    assert e.state.actors[OWNER].current_hp == hp[OWNER]
    assert {v.actor_id for v in e.events if v.event_type=='SAVE_ROLLED'} == {ALLY,FOE}
    paid=[v for v in events(e,'RESOURCE_SPENT') if v.payload['resource_id']==FOCUS]
    assert len(paid)==1 and paid[0].payload['amount']==1
    assert not events(e,'ATTACK_ROLLED')
    assert not e.state.actors[FOE].modifiers


@pytest.mark.parametrize('reason', ['stowed','focus','level'])
def test_cyclone_admission_requires_readied_pair_focus_and_cl5(tmp_path, reason):
    def prepare(b):
        setup(b)
        if reason=='focus':
            for r in b[0]['actor_template']['resources']:
                if r['resource_id']==FOCUS:r['initial']=0
            seal(b[0])
    combat,table,mid=fixture(tmp_path,[T+'CYCLONE_CUT'],cl=4 if reason=='level' else 15,
        owner_kit=kit('duan_jian','bi_shou'),foe_position={'x':3,'y':5},bundle_transform=prepare)
    if reason=='stowed':
        settle(table,mid,candidate(combat,mid,'Stow Bi Shou (Dagger) (frees 1 hand; no Action)').candidate_id)
    e=reload(tmp_path,mid)
    assert not [c for c in e.legal_candidates() if c.display_name=='Cyclone Cut']
    assert not events(e,'RESOURCE_SPENT')


def weapon(combat,mid,item,suffix=''):
    e=combat._load_session(mid).engine
    return next(c for c in e.legal_candidates() if c.source_definition_id.endswith('.weapon.'+item+suffix) and c.target_ids==(FOE,))


@pytest.mark.parametrize('owned,focus', [(True,True),(False,True),(True,False)])
def test_asynchronous_choice_normal_die_and_type_preserves_weapon_bonus_and_expires(tmp_path,owned,focus):
    def prepare(b):
        setup(b)
        if not focus:
            for r in b[0]['actor_template']['resources']:
                if r['resource_id']==FOCUS:r['initial']=0
        seal(b[0])
    combat,table,mid=fixture(tmp_path,[T+'ASYNCHRONOUS_SWING'] if owned else [],
        owner_kit=kit('duan_jian','bi_shou'),foe_position={'x':3,'y':5},bundle_transform=prepare)
    settle(table,mid,weapon(combat,mid,'duan_jian').candidate_id)
    prompts=settle(table,mid,weapon(combat,mid,'bi_shou','#offhand').candidate_id,
        {'choice:needle.async_die':'6','choice:needle.async_type':'SLASHING'})
    e=reload(tmp_path,mid)
    rolls=events(e,'DAMAGE_ROLLED')
    assert len(rolls)>=2
    assert rolls[-1].payload['expression'].startswith('1d6' if owned and focus else '1d4')
    assert rolls[-1].payload['modifier']==0
    commits=events(e,'DAMAGE_COMMITTED')
    if owned and focus:
        assert commits[-1].payload['damage_type']=='SLASHING'
        assert {p['context']['reaction_source_id'] for p in prompts}>={'choice:needle.async_die','choice:needle.async_type'}
        assert 'dw_async_choice' in e.state.actors[OWNER].turn_flags
        # The Lead weapon also uses the selected type on subsequent attacks this turn.
        # There is no additional Attack action: next turn must remove the choice.
    else:
        assert not any(p['context']['reaction_source_id'].startswith('choice:needle.async_') for p in prompts)
        assert 'dw_async_choice' not in e.state.actors[OWNER].turn_flags
    turn(table,mid,FOE);turn(table,mid,OWNER)
    assert 'dw_async_choice' not in reload(tmp_path,mid).state.actors[OWNER].turn_flags


@pytest.mark.parametrize('die,kind', [('4','PIERCING'),('6','SLASHING')])
def test_asynchronous_player_choice_changes_both_weapons_and_critical_dice_only(tmp_path,die,kind):
    import copy
    def prepare(b):
        setup(b)
        basics=[a for a in b[0]['action_catalog'] if '.weapon.' in a['source_definition_id']
                and '#' not in a['source_definition_id'] and a['display_name'].endswith(' attack')]
        for a in basics:
            a=copy.deepcopy(a)
            a['source_definition_id'] += '#test_repeat'
            a['display_name'] = 'Repeat '+a['display_name']
            a['economy']='NONE'
            a['parameters']['free_primary']=True  # Synthetic free repeat for this scenario.
            a['parameters']['typed']['effects'][0]['count']=1
            b[0]['action_catalog'].append(a)
            b[0]['actor_template']['action_ids'].append(a['source_definition_id'])
        add_action(b[0], 'Paralyze', [{'type':'condition','condition':'paralyzed',
                   'applies_to':'target','expires_on':'UNTIL_REMOVED'}])
        seal(b[0])
    combat,table,mid=fixture(tmp_path,[T+'ASYNCHRONOUS_SWING'],owner_kit=kit('duan_jian','bi_shou'),
                            foe_position={'x':3,'y':5},bundle_transform=prepare)
    settle(table,mid,candidate(combat,mid,'Paralyze',target=FOE).candidate_id)
    settle(table,mid,weapon(combat,mid,'duan_jian').candidate_id)
    prompts=settle(table,mid,weapon(combat,mid,'bi_shou','#offhand').candidate_id,
                   {'choice:needle.async_die':die,'choice:needle.async_type':kind})
    e=reload(tmp_path,mid)
    assert sorted(o['id'] for p in prompts if p['context']['reaction_source_id']=='choice:needle.async_die'
                  for o in p['choice']['options'])==['4','6']
    assert set(o['id'] for p in prompts if p['context']['reaction_source_id']=='choice:needle.async_type'
               for o in p['choice']['options'])=={'SLASHING','PIERCING'}
    for item in ['duan_jian','bi_shou']:
        settle(table,mid,weapon(combat,mid,item,'#test_repeat').candidate_id,
               {'choice:needle.async_die':die,'choice:needle.async_type':kind})
        e=reload(tmp_path,mid)
        packet=events(e,'DAMAGE_ROLLED')[-1]
        assert packet.payload['expression'].startswith('2d'+die)
        assert len(packet.payload['dice'])==2
        # The original positive ability bonus belongs to each Lead weapon.
        assert packet.payload['modifier']>0
        assert events(e,'DAMAGE_COMMITTED')[-1].payload['damage_type']==kind

@pytest.mark.parametrize('choice,save,pays', [('shove_prone','DEX',True),('shove_push','DEX',True),(None,'DEX',False),('shove_prone','STR',True)])
def test_highlow_second_hit_shove_owner_choice_target_save_and_payment(tmp_path,choice,save,pays):
    def prepare(b):
        setup(b)
        b[2]['actor_template']['saving_throws']['DEX']=-100
        b[2]['actor_template']['saving_throws']['STR']=100
        seal(b[2])
    combat,table,mid=fixture(tmp_path,[T+'HIGH_LOW_COMBINATION'],owner_kit=kit('duan_jian','bi_shou'),
                            foe_position={'x':3,'y':5},bundle_transform=prepare)
    e=reload(tmp_path,mid)
    pos=e.state.actors[FOE].position
    lead=e.action_catalog[weapon(combat,mid,'duan_jian').source_definition_id]
    expected_attacks=int(lead.parameters['typed']['effects'][0].get('count') or 1)+1
    prompts=settle(table,mid,weapon(combat,mid,'duan_jian').candidate_id)
    assert not any(p['context']['reaction_source_id']=='choice:needle.highlow_shove' for p in prompts)
    prompts=settle(table,mid,weapon(combat,mid,'bi_shou','#offhand').candidate_id,
                   {'choice:needle.highlow_shove':choice,'choice:needle.save_choice':save})
    e=reload(tmp_path,mid)
    spent=[v for v in events(e,'RESOURCE_SPENT') if v.source_definition_id==T+'HIGH_LOW_COMBINATION']
    assert len(spent)==int(pays)
    assert all(v.payload['resource_id']==FOCUS and v.payload['amount']==1 for v in spent)
    assert any(p['context']['reactor_id']==OWNER for p in prompts)
    if pays:
        assert any(p['context']['reactor_id']==FOE and p['context']['reaction_source_id']=='choice:needle.save_choice' for p in prompts)
        assert e.state.actors[OWNER].turn_flags['dw_highlow_used']==1
    prone=any(c.condition_id=='condition:typed.prone' for c in e.state.actors[FOE].conditions.values())
    assert prone == (pays and choice=='shove_prone' and save=='DEX')
    assert (e.state.actors[FOE].position!=pos)==(pays and choice=='shove_push' and save=='DEX')
    answer=e.action_catalog[next(a.source_definition_id for a in e.action_catalog.values() if a.owner_id==OWNER and a.source_definition_id.endswith('.weapon.bi_shou#offhand'))]
    assert e.state.actors[OWNER].bonus_action_available == (answer.economy != 'BONUS_ACTION')
    # No extra weapon attack came from the Shove's original Attack-action follow-ups.
    assert len(events(e,'ATTACK_ROLLED'))==expected_attacks


@pytest.mark.parametrize('owned,focus',[(False,True),(True,False)])
def test_highlow_no_ownership_or_focus_means_no_question_or_payment(tmp_path,owned,focus):
    def prepare(b):
        setup(b)
        if not focus:
            for r in b[0]['actor_template']['resources']:
                if r['resource_id']==FOCUS:r['initial']=0
            for a in b[0]['action_catalog']:
                if a['source_definition_id'].endswith('.weapon.bi_shou#offhand'):
                    a['parameters']['typed']['effects'][0]['on_hit'].append(
                        {'type':'spend_resource','resource_id':FOCUS,'flat':1,'applies_to':'self'})
        seal(b[0])
    combat,table,mid=fixture(tmp_path,[T+'HIGH_LOW_COMBINATION'] if owned else [],
        owner_kit=kit('duan_jian','bi_shou'),foe_position={'x':3,'y':5},bundle_transform=prepare)
    settle(table,mid,weapon(combat,mid,'duan_jian').candidate_id)
    prompts=settle(table,mid,weapon(combat,mid,'bi_shou','#offhand').candidate_id)
    assert not any(p['context']['reaction_source_id']=='choice:needle.highlow_shove' for p in prompts)
    assert not [v for v in events(reload(tmp_path,mid),'RESOURCE_SPENT') if v.source_definition_id==T+'HIGH_LOW_COMBINATION']

@pytest.mark.parametrize('pick',['shove_push','shove_prone'])
def test_highlow_ai_uses_trigger_on_enemy_with_ally_in_range(tmp_path,pick):
    combat,table,mid=fixture(tmp_path,[T+'HIGH_LOW_COMBINATION'],owner_kit=kit('duan_jian','bi_shou'),
        foe_position={'x':3,'y':5},bundle_transform=setup)
    settle(table,mid,weapon(combat,mid,'duan_jian').candidate_id)
    before=reload(tmp_path,mid).state.actors[ALLY].model_dump(mode='json')
    combat.set_controller_mode(mid,actor_id=OWNER,controller_mode='LOCAL_AUTO')
    cid=weapon(combat,mid,'bi_shou','#offhand').candidate_id
    from combat.gate4_adapters import ManualControllerAdapter
    real=combat.controller
    observed=[]
    class Controller:
        def choose_primary_action(self,context):
            return ManualControllerAdapter(lambda _: (cid,())).choose_primary_action(context)
        def choose_reaction(self,context):
            result=real.choose_reaction(context)
            if context.reaction_source_id=='choice:needle.highlow_shove':
                observed.append(context)
                assert context.reactor_id==OWNER and pick in context.legal_option_ids
                decision=result.decision.model_copy(update={'selection':'USE','option_ids':(pick,)})
                scores=tuple(s.model_copy(update={'total':int(s.candidate_id.endswith(':USE')),
                    'option_ids':(pick,) if s.candidate_id.endswith(':USE') else (), 'components':()})
                             for s in result.record.scored_alternatives)
                record=result.record.model_copy(update={'controller_id':'test:known_shove',
                    'selected_candidate_id':f'reaction:{context.reaction_source_id}:USE',
                    'selected_option_ids':(pick,), 'selected_reaction':decision,
                    'scored_alternatives':scores,'explanation':'Choose an offered Shove option against the perceived struck enemy.'})
                return result.model_copy(update={'decision':decision,'record':record})
            return result
        def __getattr__(self,name):return getattr(real,name)
    combat.controller=Controller()
    try:
        settle(table,mid,cid,auto=True)
    finally:
        combat.controller=real
    e=reload(tmp_path,mid)
    assert observed
    assert e.state.actors[ALLY].model_dump(mode='json')==before
    assert len([v for v in events(e,'RESOURCE_SPENT') if v.source_definition_id==T+'HIGH_LOW_COMBINATION'])==1
    assert e.state.actors[OWNER].turn_flags['dw_highlow_used']==1


def test_highlow_lead_misses_do_not_trigger_shove(tmp_path):
    def prepare(b):
        setup(b)
        b[2]['actor_template']['armor_class']=100
        seal(b[2])
        add_action(b[0],'Lower guard',[{'type':'ac_bonus','applies_to':'target','flat':-100,'duration':'one_minute'}])
    combat,table,mid=fixture(tmp_path,[T+'HIGH_LOW_COMBINATION'],owner_kit=kit('duan_jian','bi_shou'),
                            foe_position={'x':3,'y':5},bundle_transform=prepare)
    settle(table,mid,weapon(combat,mid,'duan_jian').candidate_id)
    settle(table,mid,candidate(combat,mid,'Lower guard',target=FOE).candidate_id)
    prompts=settle(table,mid,weapon(combat,mid,'bi_shou','#offhand').candidate_id)
    assert not any(p['context']['reaction_source_id']=='choice:needle.highlow_shove' for p in prompts)
    assert not [v for v in events(reload(tmp_path,mid),'RESOURCE_SPENT') if v.source_definition_id==T+'HIGH_LOW_COMBINATION']


def test_highlow_too_large_target_is_not_offered_and_cost_is_not_spent(tmp_path):
    def prepare(b):
        setup(b)
        b[2]['actor_template']['size_category']='Huge'
        seal(b[2])
    combat,table,mid=fixture(tmp_path,[T+'HIGH_LOW_COMBINATION'],owner_kit=kit('duan_jian','bi_shou'),
        positions={OWNER:{'x':1,'y':1},ALLY:{'x':1,'y':2},FOE:{'x':2,'y':1}},bundle_transform=prepare)
    settle(table,mid,weapon(combat,mid,'duan_jian').candidate_id)
    prompts=settle(table,mid,weapon(combat,mid,'bi_shou','#offhand').candidate_id)
    assert not any(p['context']['reaction_source_id']=='choice:needle.highlow_shove' for p in prompts)
    assert not [v for v in events(reload(tmp_path,mid),'RESOURCE_SPENT') if v.source_definition_id==T+'HIGH_LOW_COMBINATION']


def test_highlow_turn_limit_and_reset_survive_reload(tmp_path):
    def prepare(b):
        import copy
        setup(b)
        b[2]['actor_template']['saving_throws']['DEX']=-100
        b[2]['actor_template']['saving_throws']['STR']=-100
        seal(b[2])
        a=copy.deepcopy(next(a for a in b[0]['action_catalog'] if a['source_definition_id'].endswith('.weapon.bi_shou#offhand')))
        a['source_definition_id'] += '_test_repeat'
        a['display_name']='Repeat Answering Weapon'
        a['economy']='NONE'
        a['parameters']['free_primary']=True  # Synthetic free repeat for this scenario.
        a['parameters']['typed'].pop('uses',None)
        for k in ['requires_turn_flag','requires_turn_flags','blocked_by_turn_flag']:
            a['parameters'].pop(k,None)
        b[0]['action_catalog'].append(a)
        b[0]['actor_template']['action_ids'].append(a['source_definition_id'])
        seal(b[0])
    combat,table,mid=fixture(tmp_path,[T+'HIGH_LOW_COMBINATION'],owner_kit=kit('duan_jian','bi_shou'),
                            foe_position={'x':3,'y':5},bundle_transform=prepare)
    def activate():
        settle(table,mid,weapon(combat,mid,'duan_jian').candidate_id)
        settle(table,mid,weapon(combat,mid,'bi_shou','#offhand').candidate_id,
               {'choice:needle.highlow_shove':'shove_prone','choice:needle.save_choice':'DEX'})
    activate()
    settle(table,mid,candidate(combat,mid,'Hold focus').candidate_id)
    prompts=settle(table,mid,candidate(combat,mid,'Repeat Answering Weapon',target=FOE).candidate_id)
    assert not any(p['context']['reaction_source_id']=='choice:needle.highlow_shove' for p in prompts)
    e=reload(tmp_path,mid)
    assert len([v for v in events(e,'RESOURCE_SPENT') if v.source_definition_id==T+'HIGH_LOW_COMBINATION'])==1
    assert e.state.actors[OWNER].resources[FOCUS]==1
    turn(table,mid,FOE);turn(table,mid,OWNER)
    assert 'dw_highlow_used' not in reload(tmp_path,mid).state.actors[OWNER].turn_flags
    activate()
    e=reload(tmp_path,mid)
    assert len([v for v in events(e,'RESOURCE_SPENT') if v.source_definition_id==T+'HIGH_LOW_COMBINATION'])==2


def test_asynchronous_can_choose_again_and_retains_latest_choice_without_focus(tmp_path):
    import copy
    def prepare(b):
        setup(b)
        for a in list(b[0]['action_catalog']):
            if '.weapon.' in a['source_definition_id'] and '#' not in a['source_definition_id'] and a['display_name'].endswith(' attack'):
                a=copy.deepcopy(a);a['source_definition_id']+='#test_repeat';a['display_name']='Repeat '+a['display_name'];a['economy']='NONE'
                a['parameters']['free_primary']=True  # Synthetic free repeat for this scenario.
                a['parameters']['typed']['effects'][0]['count']=1
                b[0]['action_catalog'].append(a);b[0]['actor_template']['action_ids'].append(a['source_definition_id'])
        add_action(b[0],'Expend focus',[{'type':'spend_resource','resource_id':FOCUS,'flat':1,'applies_to':'self'}],target='SELF')
        seal(b[0])
    combat,table,mid=fixture(tmp_path,[T+'ASYNCHRONOUS_SWING'],owner_kit=kit('duan_jian','bi_shou'),
                            foe_position={'x':3,'y':5},bundle_transform=prepare)
    settle(table,mid,weapon(combat,mid,'duan_jian').candidate_id)
    settle(table,mid,weapon(combat,mid,'bi_shou','#offhand').candidate_id,
           {'choice:needle.async_die':'6','choice:needle.async_type':'SLASHING'})
    prompts=settle(table,mid,weapon(combat,mid,'duan_jian','#test_repeat').candidate_id,
           {'choice:needle.async_die':'4','choice:needle.async_type':'PIERCING'})
    assert any(p['context']['reaction_source_id']=='choice:needle.async_die' for p in prompts)
    e=reload(tmp_path,mid)
    assert events(e,'DAMAGE_ROLLED')[-1].payload['expression'].startswith('1d4')
    assert events(e,'DAMAGE_COMMITTED')[-1].payload['damage_type']=='PIERCING'
    settle(table,mid,candidate(combat,mid,'Expend focus').candidate_id)
    prompts=settle(table,mid,weapon(combat,mid,'bi_shou','#test_repeat').candidate_id)
    assert not any(p['context']['reaction_source_id'].startswith('choice:needle.async_') for p in prompts)
    e=reload(tmp_path,mid)
    assert events(e,'DAMAGE_ROLLED')[-1].payload['expression'].startswith('1d4')
    assert events(e,'DAMAGE_COMMITTED')[-1].payload['damage_type']=='PIERCING'


@pytest.mark.parametrize('earlier', ['no_focus', 'decline'])
def test_highlow_fresh_hit_reoffers_until_used_after_cold_reload(tmp_path, earlier):
    import copy
    def prepare(b):
        setup(b)
        for ability in ['DEX', 'STR']:
            b[2]['actor_template']['saving_throws'][ability] = -100
        seal(b[2])
        if earlier == 'no_focus':
            for r in b[0]['actor_template']['resources']:
                if r['resource_id'] == FOCUS:
                    r['initial'] = 0
            # Native critical follow-ups can restore Focus; keep the initial Answering hit unavailable.
            for action in b[0]['action_catalog']:
                if action['source_definition_id'].endswith('.weapon.bi_shou#offhand'):
                    action['parameters']['typed']['effects'][0]['on_hit'].append(
                        {'type':'spend_resource', 'resource_id':FOCUS, 'flat':1, 'applies_to':'self'})
        a = copy.deepcopy(next(a for a in b[0]['action_catalog']
                               if a['source_definition_id'].endswith('.weapon.bi_shou#offhand')))
        a['source_definition_id'] += '_test_repeat'
        a['parameters']['typed']['effects'][0]['on_hit'] = [r for r in a['parameters']['typed']['effects'][0]['on_hit'] if r.get('type') != 'spend_resource']
        a['display_name'] = 'Fresh Answering hit'
        a['economy'] = 'NONE'
        a['parameters']['free_primary'] = True  # Synthetic free repeat for this scenario.
        a['parameters']['typed'].pop('uses', None)
        for k in ['requires_turn_flag', 'requires_turn_flags', 'blocked_by_turn_flag']:
            a['parameters'].pop(k, None)
        b[0]['action_catalog'].append(a)
        b[0]['actor_template']['action_ids'].append(a['source_definition_id'])
        seal(b[0])
    combat, table, mid = fixture(tmp_path, [T+'HIGH_LOW_COMBINATION'],
        owner_kit=kit('duan_jian', 'bi_shou'), foe_position={'x':3, 'y':5}, bundle_transform=prepare)
    settle(table, mid, weapon(combat, mid, 'duan_jian').candidate_id)
    prompts = settle(table, mid, weapon(combat, mid, 'bi_shou', '#offhand').candidate_id,
                     {'choice:needle.highlow_shove': None})
    assert any(p['context']['reaction_source_id'] == 'choice:needle.highlow_shove'
               for p in prompts) == (earlier == 'decline')
    e = reload(tmp_path, mid)
    assert not e.state.actors[OWNER].turn_flags.get('dw_highlow_used')
    assert not [v for v in events(e, 'RESOURCE_SPENT') if v.source_definition_id == T+'HIGH_LOW_COMBINATION']
    if earlier == 'no_focus':
        settle(table, mid, candidate(combat, mid, 'Hold focus').candidate_id)
    # Replace the active service too: the fresh hit starts from persisted provenance, not a warm engine.
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    from tests.worker2_support import ROOT
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    prompts = settle(table, mid, candidate(combat, mid, 'Fresh Answering hit', target=FOE).candidate_id,
        {'choice:needle.highlow_shove':'shove_prone', 'choice:needle.save_choice':'DEX'})
    assert any(p['context']['reaction_source_id'] == 'choice:needle.highlow_shove' for p in prompts)
    e = reload(tmp_path, mid)
    assert e.state.actors[OWNER].turn_flags['dw_highlow_used'] == 1
    assert e.state.actors[OWNER].resources[FOCUS] == 0
    assert len([v for v in events(e, 'RESOURCE_SPENT') if v.source_definition_id == T+'HIGH_LOW_COMBINATION']) == 1
    assert any(c.condition_id == 'condition:typed.prone' for c in e.state.actors[FOE].conditions.values())


@pytest.mark.parametrize('items,stow', [(('duan_jian','bi_shou'), 'Bi Shou (Dagger)'),
                                      (('hu_die_dao',), 'Hu Die Dao (Butterfly Sabers)')])
def test_shared_pair_enumeration_tracks_service_grips_after_reload(tmp_path, items, stow):
    combat, table, mid = fixture(tmp_path, [T+'CYCLONE_CUT', T+'GREATER_BLADES'], owner_kit=kit(*items),
        foe_position={'x':3,'y':5}, bundle_transform=setup)
    settle(table, mid, candidate(combat, mid, 'Hold focus').candidate_id)
    reload(tmp_path, mid)
    from combat.ext.qualifying_pairs import qualifying_pairs, qualifying_pair
    from combat.ext import martial_dual_wielding, zz_dual_wielding
    # Both existing boolean consumers and exact-damage consumers use the public eligibility seam.
    assert martial_dual_wielding.qualifying_pair is qualifying_pair
    assert zz_dual_wielding.qualifying_pairs is qualifying_pairs
    def check(ready):
        e = reload(tmp_path, mid)
        actor = e.state.actors[OWNER]
        pairs = qualifying_pairs(e, actor)
        assert qualifying_pair(e, actor) == bool(pairs) == ready
        assert [tuple(w['id'] for w in p) for p in zz_dual_wielding.readied_pairs(e, actor)] == pairs
        assert any(e.action_catalog.get(c.source_definition_id) is not None and e.action_catalog[c.source_definition_id].display_name == 'Cyclone Cut' for c in e.legal_candidates()) == ready
    check(True)
    settle(table, mid, candidate(combat, mid, f'Stow {stow} (frees {2 if len(items)==1 else 1} hand{ "s" if len(items)==1 else ""}; no Action)').candidate_id)
    check(False)
