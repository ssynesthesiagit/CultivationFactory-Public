"""Printed Daemonic combat clauses through table commits and cold reducer reloads."""
import pytest
from tests.cw2_service_support import add_action, seal
from tests.worker2_support import OWNER, ALLY, FOE, candidate, fixture, reload, settle, turn, sealed_native_attack
from tests.test_r9i_karma_persistence import end_turn
from tests.test_auto103_daemonic import sow, cycle

P = 'TAL_DAEMONIC_CULTIVATION_'
ESSENCE = 'resource:named.devoured_essence'
CORRUPTION = 'resource:named.corruption'
CHOICE = 'choice:needle.bloodless_devouring'


def prepare(bundles):
    for r in bundles[0]['actor_template']['resources']:
        if r['resource_id'] == ESSENCE: r.update(initial=4, maximum=12)
        if r['resource_id'] == CORRUPTION: r.update(initial=3, maximum=10)
    bundles[2]['actor_template']['maximum_hp'] = 100
    bundles[2]['actor_template']['armor_class'] = 1
    bundles[2]['actor_template']['creature_types'] = ['Undead']
    sealed_native_attack(bundles[0], 'Native claws', count=1, sides=2, modifier=2, attacks=2)
    add_action(bundles[0], 'Wound', [{'type':'damage','flat':60,'applies_to':'target','damage_types':['force']}])
    add_action(bundles[0], 'Typed claws', [{'type':'damage','flat':3,'applies_to':'target','damage_types':['force']}])
    seal(bundles[0]); seal(bundles[2])


@pytest.mark.parametrize('attack', ['Native claws', 'Typed claws'])
@pytest.mark.parametrize('choice', ['temporary_hp', 'corruption', None])
def test_bloodless_all_damage_uses_owned_numbers_and_one_payment(tmp_path, attack, choice):
    combat, table, mid = fixture(tmp_path, [P+'BLOODLESS_DEVOURING'], bundle_transform=prepare)
    settle(table, mid, candidate(combat, mid, 'Wound', target=FOE).candidate_id, {CHOICE: None})
    # Damage into the printed below-half window through a real prior commit.
    add = candidate(combat, mid, 'Typed claws', target=FOE)
    prompts = settle(table, mid, add.candidate_id, {CHOICE: None})
    before = reload(tmp_path, mid).state.actors[OWNER]
    assert before.resources[ESSENCE] == 4
    prompts = settle(table, mid, candidate(combat, mid, attack, target=FOE).candidate_id, {CHOICE: choice})
    engine = reload(tmp_path, mid); owner = engine.state.actors[OWNER]
    assert owner.resources[ESSENCE] == 4-int(choice is not None)
    assert owner.resources[CORRUPTION] == 3-int(choice == 'corruption')
    if choice == 'temporary_hp': assert owner.temporary_hp == 8
    asked = [p for p in prompts if p['context']['reaction_source_id'] == CHOICE]
    assert asked
    assert attack in asked[0]['trigger']
    assert asked[0]['cost'] == '1 Devoured Essence'
    if choice is not None: assert len(asked) == 1


def test_bloodless_does_not_trigger_when_damage_crosses_half(tmp_path):
    def healthy(b):
        prepare(b); seal(b[2])
        add_action(b[0], 'Deep wound', [{'type':'damage','flat':60,'applies_to':'target','damage_types':['force']}])
    combat, table, mid = fixture(tmp_path, [P+'BLOODLESS_DEVOURING'], bundle_transform=healthy)
    prompts = settle(table, mid, candidate(combat, mid, 'Deep wound', target=FOE).candidate_id)
    assert not [p for p in prompts if p['context']['reaction_source_id'] == CHOICE]
    assert reload(tmp_path, mid).state.actors[OWNER].resources[ESSENCE] == 4


def test_bloodless_old_row_keeps_native_gap(tmp_path):
    def legacy(b):
        prepare(b)
        for row in b[0]['typed_passives']:
            if row.get('block') == 'bloodless_devouring': row.pop('a2_packets', None); row.pop('choice_owner', None)
        seal(b[0])
    combat, table, mid = fixture(tmp_path, [P+'BLOODLESS_DEVOURING'], bundle_transform=legacy)
    settle(table, mid, candidate(combat, mid, 'Wound', target=FOE).candidate_id, {CHOICE: None})
    prompts = settle(table, mid, candidate(combat, mid, 'Native claws', target=FOE).candidate_id)
    assert not [p for p in prompts if p['context']['reaction_source_id'] == CHOICE]
    assert reload(tmp_path, mid).state.actors[OWNER].resources[ESSENCE] == 4


def form_prepare(b):
    prepare(b)
    add_action(b[0], 'Gain Essence', [{'type':'gain_resource','applies_to':'self','resource_id':ESSENCE,'flat':1}], target='SELF')
    add_action(b[0], 'Spend Essence', [{'type':'spend_resource','applies_to':'self','resource_id':ESSENCE,'flat':1}], target='SELF')
    add_action(b[0], 'End Incarnation', [{'type':'remove_condition','applies_to':'self','condition':'a2_inner_incarnation'}], target='SELF')


def test_inner_bonus_once_per_round_survives_reload_and_ends(tmp_path):
    combat, table, mid = fixture(tmp_path, [P+'INNER_DEMON_INCARNATION'], bundle_transform=form_prepare)
    settle(table, mid, candidate(combat, mid, 'Inner Demon Incarnation').candidate_id)
    settle(table, mid, candidate(combat, mid, 'Gain Essence').candidate_id)
    assert reload(tmp_path, mid).state.actors[OWNER].resources[ESSENCE] == 6
    settle(table, mid, candidate(combat, mid, 'Gain Essence').candidate_id)
    assert reload(tmp_path, mid).state.actors[OWNER].resources[ESSENCE] == 7
    cycle(table, mid, OWNER)
    settle(table, mid, candidate(combat, mid, 'Gain Essence').candidate_id)
    assert reload(tmp_path, mid).state.actors[OWNER].resources[ESSENCE] == 9
    settle(table, mid, candidate(combat, mid, 'End Incarnation').candidate_id)
    assert reload(tmp_path, mid).state.actors[OWNER].resources[CORRUPTION] == 4
    settle(table, mid, candidate(combat, mid, 'Gain Essence').candidate_id)
    assert reload(tmp_path, mid).state.actors[OWNER].resources[ESSENCE] == 10


@pytest.mark.parametrize('remaining,corruption', [(0,5), (2,4)])
def test_inner_ending_at_printed_minute_settles_once(tmp_path, remaining, corruption):
    def configure(b):
        form_prepare(b)
        for r in b[0]['actor_template']['resources']:
            if r['resource_id'] == ESSENCE: r['initial'] = remaining
        seal(b[0])
    combat, table, mid = fixture(tmp_path, [P+'INNER_DEMON_INCARNATION'], bundle_transform=configure)
    settle(table, mid, candidate(combat, mid, 'Inner Demon Incarnation').candidate_id)
    for _ in range(10): cycle(table, mid, OWNER)
    engine = reload(tmp_path, mid)
    assert not any(c.condition_id == 'condition:typed.a2_inner_incarnation' for c in engine.state.actors[OWNER].conditions.values())
    assert engine.state.actors[OWNER].resources[CORRUPTION] == corruption
    cycle(table, mid, OWNER)
    assert reload(tmp_path, mid).state.actors[OWNER].resources[CORRUPTION] == corruption


def test_furnace_spend_only_while_seeded_once_turn_and_owned(tmp_path):
    combat, table, mid = fixture(tmp_path, [P+'SECOND_FURNACE_DEMON_HEART',P+'DEMON_SEED'], bundle_transform=form_prepare)
    settle(table, mid, candidate(combat, mid, 'Spend Essence').candidate_id)
    assert reload(tmp_path, mid).state.actors[OWNER].temporary_hp == 0
    sow(combat, table, mid)
    # Seed's temporary HP is larger; consume it through an ordinary enemy packet.
    turn(table, mid, FOE)
    turn(table, mid, OWNER)
    settle(table, mid, candidate(combat, mid, 'Spend Essence').candidate_id)
    engine = reload(tmp_path, mid)
    grants = [e for e in engine.events if e.event_type == 'TEMP_HP_GRANTED' and e.source_definition_id == P+'SECOND_FURNACE_DEMON_HEART']
    assert len(grants) == 1
    settle(table, mid, candidate(combat, mid, 'Spend Essence').candidate_id)
    grants = [e for e in reload(tmp_path, mid).events if e.event_type == 'TEMP_HP_GRANTED' and e.source_definition_id == P+'SECOND_FURNACE_DEMON_HEART']
    assert len(grants) == 1


RECOVERY_CHOICE = 'choice:needle.heaven_spiting'


def recovery_prepare(b):
    form_prepare(b)
    b[0]['actor_template']['resources'].append({'resource_id':'resource:core.stamina','initial':6,'maximum':6})
    add_action(b[0], 'Lie down', [{'type':'condition','applies_to':'self','condition':'prone','expires_on':'UNTIL_REMOVED'}], target='SELF')
    add_action(b[2], 'Lethal blast', [{'type':'damage','applies_to':'target','flat':120,'damage_types':['force']}])
    seal(b[0])


@pytest.mark.parametrize('pool', ['resource:core.qi','resource:core.stamina',ESSENCE,None])
def test_recovery_asks_pool_and_settles_after_native_or_typed_damage(tmp_path, pool):
    combat, table, mid = fixture(tmp_path, [P+'HEAVEN_SPITING_RECOVERY',P+'DEMON_SEED'], bundle_transform=recovery_prepare)
    sow(combat, table, mid)
    settle(table, mid, candidate(combat, mid, 'Lie down').candidate_id)
    turn(table, mid, FOE)
    before = reload(tmp_path, mid).state.actors[OWNER]
    prompts = settle(table, mid, candidate(combat, mid, 'Lethal blast', target=OWNER).candidate_id,
                     {RECOVERY_CHOICE:pool})
    engine = reload(tmp_path, mid); owner = engine.state.actors[OWNER]
    asked = [p for p in prompts if p['context']['reaction_source_id'] == RECOVERY_CHOICE]
    assert asked and 'Lethal blast' in asked[0]['trigger']
    assert 'Corruption' in asked[0]['trigger'] and 'Long Rest' in asked[0]['trigger']
    if pool is None:
        assert owner.current_hp == 0
        assert owner.resources[CORRUPTION] == before.resources[CORRUPTION]
        assert owner.resources[ESSENCE] == before.resources[ESSENCE]
    else:
        assert owner.current_hp == 1 and owner.temporary_hp == 8
        assert not any(c.condition_id == 'condition:typed.prone' for c in owner.conditions.values())
        assert owner.resources[pool] == before.resources[pool]-3
        assert owner.resources[CORRUPTION] == before.resources[CORRUPTION]+1
        assert not owner.reaction_available
        damage = next(e for e in engine.events if e.event_type=='DAMAGE_COMMITTED' and OWNER in e.target_ids)
        follow = next(e for e in engine.events if e.event_type=='TEMP_HP_GRANTED' and e.source_definition_id==P+'HEAVEN_SPITING_RECOVERY')
        assert engine.events.index(damage) < engine.events.index(follow)
        turn(table, mid, OWNER); cycle(table, mid, FOE)
        again = settle(table, mid, candidate(combat, mid, 'Lethal blast', target=OWNER).candidate_id)
        assert not [p for p in again if p['context']['reaction_source_id'] == RECOVERY_CHOICE]
        assert reload(tmp_path, mid).state.actors[OWNER].current_hp == 0


@pytest.mark.parametrize('seeded,essence,qi', [(False,4,100), (True,2,0)])
def test_recovery_no_seed_or_no_affordable_pool_offers_nothing(tmp_path, seeded, essence, qi):
    def configure(b):
        form_prepare(b)
        for r in b[0]['actor_template']['resources']:
            if r['resource_id'] == ESSENCE: r['initial']=essence
            if r['resource_id'] == 'resource:core.qi': r['initial']=qi
        add_action(b[0], 'Test Seed', [{'type':'condition','applies_to':'self','condition':'stance.demon_seed','expires_on':'UNTIL_REMOVED'}],target='SELF')
        add_action(b[2], 'Lethal blast', [{'type':'damage','applies_to':'target','flat':120,'damage_types':['force']}])
        seal(b[0])
    combat, table, mid = fixture(tmp_path, [P+'HEAVEN_SPITING_RECOVERY'], bundle_transform=configure)
    if seeded: settle(table, mid, candidate(combat, mid, 'Test Seed').candidate_id)
    turn(table, mid, FOE)
    prompts=settle(table, mid, candidate(combat, mid, 'Lethal blast',target=OWNER).candidate_id)
    assert not [p for p in prompts if p['context']['reaction_source_id']==RECOVERY_CHOICE]
    assert reload(tmp_path, mid).state.actors[OWNER].current_hp==0


@pytest.mark.parametrize('accept', [True, False])
@pytest.mark.parametrize('corruption', [3, 9, 10])
def test_furnace_empty_cp_trade_is_optional_and_committed(tmp_path, accept, corruption):
    def configure(b):
        form_prepare(b)
        for resource in b[0]['actor_template']['resources']:
            if resource['resource_id'] == CORRUPTION:
                resource['initial'] = corruption
        add_action(b[0], 'Empty CP', [{'type':'spend_resource','applies_to':'self','resource_id':'resource:core.qi','flat':99}],target='SELF')
    combat, table, mid = fixture(tmp_path, [P+'SECOND_FURNACE_DEMON_HEART',P+'DEMON_SEED'], bundle_transform=configure)
    sow(combat, table, mid)
    settle(table, mid, candidate(combat, mid, 'Empty CP').candidate_id)
    before = reload(tmp_path, mid).state.actors[OWNER]
    assert before.resources['resource:core.qi']==0
    prompts=[]
    for _ in range(8):
        prompts += settle(table, mid, table.state(mid)['menu']['end_turn'],
                          {'choice:needle.second_furnace': 'accept' if accept else None})
        if table.state(mid)['menu']['actor_id']==OWNER: break
    asked=[p for p in prompts if p['context']['reaction_source_id']=='choice:needle.second_furnace']
    engine=reload(tmp_path,mid); owner=engine.state.actors[OWNER]
    paid = int(accept and corruption < 10)
    assert owner.resources[ESSENCE]==before.resources[ESSENCE]+paid
    assert owner.resources[CORRUPTION]==before.resources[CORRUPTION]+paid
    assert owner.action_available and owner.reaction_available
    if corruption < 10:
        assert asked and '1 Corruption' in asked[0]['trigger'] and 'no Action' in asked[0]['choice']['options'][0]['label']
    else:
        assert not asked
        riders = [e for e in engine.events if e.event_type == 'GM_RIDER'
                  and e.source_definition_id == P+'SECOND_FURNACE_DEMON_HEART']
        assert riders and 'Demonic Debt' in riders[-1].payload['rider']
        assert not [e for e in engine.events if e.event_type == 'RESOURCE_GAINED'
                    and e.source_definition_id == P+'SECOND_FURNACE_DEMON_HEART']


@pytest.mark.parametrize('incarnate',[True,False])
def test_inner_makes_native_attacks_magical_against_mundane_only_resistance(tmp_path, incarnate):
    def configure(b):
        form_prepare(b)
        b[2]['typed_passives'].append({'feature_id':'TEST:MUNDANE_WARD','block':'resistance',
                                      'kind':'resistance','damage_types':['FIRE'],'mundane_only':True})
        source=sealed_native_attack(b[0],'Native flame',damage_type='FIRE',count=1,sides=2,modifier=10)
        next(a for a in b[0]['action_catalog'] if a['source_definition_id']==source)['parameters']['typed']={'mundane':True}
        seal(b[0]);seal(b[2])
    combat,table,mid=fixture(tmp_path,[P+'INNER_DEMON_INCARNATION'],bundle_transform=configure)
    if incarnate: settle(table,mid,candidate(combat,mid,'Inner Demon Incarnation').candidate_id)
    settle(table,mid,candidate(combat,mid,'Native flame',target=FOE).candidate_id)
    e=reload(tmp_path,mid)
    packets=[ev for ev in e.events if ev.event_type=='DAMAGE_COMMITTED' and FOE in ev.target_ids
             and e.action_catalog.get(ev.source_definition_id) and e.action_catalog[ev.source_definition_id].display_name=='Native flame']
    assert len(packets)==1
    raw=int(packets[0].payload['rolled_or_pending_damage']); delivered=int(packets[0].payload['reduced_to'])
    assert delivered==(raw if incarnate else raw//2)


def test_recovery_handles_native_lethal_packet(tmp_path):
    def configure(b):
        recovery_prepare(b)
        sealed_native_attack(b[2],'Native execution',damage_type='FIRE',count=1,sides=2,modifier=100)
        b[0]['actor_template']['armor_class']=1;seal(b[0])
    combat,table,mid=fixture(tmp_path,[P+'HEAVEN_SPITING_RECOVERY',P+'DEMON_SEED'],bundle_transform=configure)
    sow(combat,table,mid);turn(table,mid,FOE)
    prompts=settle(table,mid,candidate(combat,mid,'Native execution',target=OWNER).candidate_id,{RECOVERY_CHOICE:ESSENCE})
    assert any(p['context']['reaction_source_id']==RECOVERY_CHOICE for p in prompts)
    owner=reload(tmp_path,mid).state.actors[OWNER]
    assert owner.current_hp==1 and owner.temporary_hp==8 and owner.resources[ESSENCE]==1


def test_bloodless_lethal_overkill_uses_hp_before_receipt(tmp_path):
    def configure(b):
        prepare(b)
        add_action(b[0],'Finish enemy',[{'type':'damage','applies_to':'target','flat':150,'damage_types':['force']}])
    combat,table,mid=fixture(tmp_path,[P+'BLOODLESS_DEVOURING'],bundle_transform=configure)
    settle(table,mid,candidate(combat,mid,'Wound',target=FOE).candidate_id,{CHOICE:None})
    prompts=settle(table,mid,candidate(combat,mid,'Finish enemy',target=FOE).candidate_id,{CHOICE:'corruption'})
    assert any(p['context']['reaction_source_id']==CHOICE for p in prompts)
    e=reload(tmp_path,mid)
    assert e.state.actors[FOE].current_hp==0
    spends=[ev for ev in e.events if ev.event_type=='RESOURCE_SPENT' and ev.source_definition_id==P+'BLOODLESS_DEVOURING' and ev.payload['resource_id']==ESSENCE]
    assert len(spends)==1 and spends[0].payload['amount']==1
    # The implicit base sphere also devours the defeated creature for one Essence.
    assert e.state.actors[OWNER].resources[ESSENCE]==4
    assert e.state.actors[OWNER].resources[CORRUPTION]==2


@pytest.mark.parametrize('choice', ['hp','resource:core.qi'])
def test_bloodless_native_healing_and_pool_choice_use_printed_amount(tmp_path,choice):
    def configure(b):
        prepare(b)
        add_action(b[0],'Wound self',[{'type':'damage','applies_to':'self','flat':10,'damage_types':['force']}],target='SELF')
        for r in b[0]['actor_template']['resources']:
            if r['resource_id']=='resource:core.qi':r['initial']=70
        seal(b[0])
    combat,table,mid=fixture(tmp_path,[P+'BLOODLESS_DEVOURING'],bundle_transform=configure,
                             positions={OWNER:{'x':3,'y':6},ALLY:{'x':2,'y':7},FOE:{'x':4,'y':6}})
    settle(table,mid,candidate(combat,mid,'Wound self').candidate_id,{CHOICE:None})
    settle(table,mid,candidate(combat,mid,'Wound',target=FOE).candidate_id,{CHOICE:None})
    settle(table,mid,candidate(combat,mid,'Native claws',target=FOE).candidate_id,{CHOICE:choice})
    e=reload(tmp_path,mid); owner=e.state.actors[OWNER]
    assert owner.resources[ESSENCE]==3
    assert owner.current_hp==(56 if choice=='hp' else 50)
    assert owner.resources['resource:core.qi']==70+int(choice=='resource:core.qi')
    if choice=='hp':
        heals=[ev for ev in e.events if ev.event_type=='HEALING_APPLIED' and ev.source_definition_id==P+'BLOODLESS_DEVOURING']
        assert len(heals)==1 and heals[0].payload['offered']==6


@pytest.mark.parametrize('cl,seeded,accept',[(10,True,True),(10,True,False),(9,True,True),(10,False,True)])
def test_demon_bone_turn_start_payment_heal_and_gates(tmp_path,cl,seeded,accept):
    def configure(b):
        prepare(b)
        add_action(b[0],'Wound self',[{'type':'damage','applies_to':'self','flat':20,'damage_types':['force']}],target='SELF')
    combat,table,mid=fixture(tmp_path,[P+'DEMON_BONE_REGENERATION',P+'DEMON_SEED'],cl=cl,bundle_transform=configure)
    settle(table,mid,candidate(combat,mid,'Wound self').candidate_id)
    if seeded:sow(combat,table,mid)
    prompts=[]
    for _ in range(8):
        prompts+=settle(table,mid,table.state(mid)['menu']['end_turn'],
                         {'choice:spend.demon_bone_regeneration':'1' if accept else None})
        if table.state(mid)['menu']['actor_id']==OWNER:break
    asked=[p for p in prompts if p['context']['reaction_source_id']=='choice:spend.demon_bone_regeneration']
    eligible=cl>=10 and seeded
    assert bool(asked)==eligible
    e=reload(tmp_path,mid);owner=e.state.actors[OWNER]
    assert owner.resources[ESSENCE]==4-int(eligible and accept)
    if eligible and accept:
        assert 43<=owner.current_hp<=50
        assert any(ev.event_type=='HEALING_APPLIED' and 'DEMON_BONE_REGENERATION' in ev.source_definition_id for ev in e.events)
    else:assert owner.current_hp==40


def select_native_primary(combat, mid, name, target):
    """Choose a legal visible primary; keep the shipped AI reaction controller.

    Synthetic native source IDs have no character policy priority. This fixture
    exercises LOCAL_AUTO transport/choices, not native primary policy ranking.
    """
    from combat.gate4_adapters import ManualControllerAdapter
    source = next(a.source_definition_id for a in combat._load_session(mid).engine.action_catalog.values()
                  if a.display_name == name)
    real = combat.controller

    class NativePrimary:
        def choose_primary_action(self, context):
            selected = next(c for c in context.legal_candidates
                            if c.source_definition_id == source and target in c.target_ids)
            return ManualControllerAdapter(lambda _context: (selected.candidate_id, ())).choose_primary_action(context)

        def __getattr__(self, name):
            return getattr(real, name)

    combat.controller = NativePrimary()


def test_manual_recovery_owner_is_asked_on_actual_ai_attack(tmp_path):
    def configure(b):
        recovery_prepare(b)
        source=sealed_native_attack(b[2],'AI execution',damage_type='FIRE',count=1,sides=2,modifier=100)
        b[2]['action_catalog']=[a for a in b[2]['action_catalog'] if a['source_definition_id']==source]
        b[2]['actor_template']['action_ids']=[source]
        b[2]['action_catalog'][0]['parameters']['expected_damage']=120
        b[0]['actor_template']['armor_class']=1
        b[0]['actor_template']['primary_combatant']=True
        b[1]['actor_template']['primary_combatant']=False
        seal(b[0]);seal(b[1]);seal(b[2])
    combat,table,mid=fixture(tmp_path,[P+'HEAVEN_SPITING_RECOVERY',P+'DEMON_SEED'],bundle_transform=configure,
                             seed='SEED-OWNER-FIRST',modes={OWNER:'MANUAL',ALLY:'MANUAL',FOE:'LOCAL_AUTO'},
                             positions={OWNER:{'x':3,'y':6},ALLY:{'x':2,'y':7},FOE:{'x':4,'y':6}})
    sow(combat,table,mid);turn(table,mid,FOE)
    select_native_primary(combat,mid,'AI execution',OWNER)
    answers=[]
    for _ in range(8):
        result=combat.local_step(mid,answers or None)
        assert result['status']=='AWAITING_REACTION',result
        asked=result['reaction_context']
        if asked['reaction_source_id']==RECOVERY_CHOICE:break
        answers.append({'checkpoint':asked['checkpoint'],'reactor_id':asked['reactor_id'],
                        'reaction_source_id':asked['reaction_source_id'],'selection':'DECLINE'})
    assert asked['reactor_id']==OWNER and asked['reaction_source_id']==RECOVERY_CHOICE
    assert reload(tmp_path,mid).state.actors[OWNER].resources[ESSENCE]==4
    result=combat.local_step(mid,[*answers,{'checkpoint':asked['checkpoint'],'reactor_id':OWNER,
                                  'reaction_source_id':RECOVERY_CHOICE,'selection':'USE','option_ids':[ESSENCE]}])
    assert result['status']=='COMMITTED',result
    owner=reload(tmp_path,mid).state.actors[OWNER]
    assert owner.current_hp==1 and owner.temporary_hp==8 and owner.resources[ESSENCE]==1


def test_bloodless_actual_ai_owner_pays_once_and_heals(tmp_path):
    def configure(b):
        prepare(b)
        add_action(b[0],'Wound self',[{'type':'damage','applies_to':'self','flat':10,'damage_types':['force']}],target='SELF')
        b[0]['action_catalog']=[a for a in b[0]['action_catalog'] if a['display_name'] in ('Wound','Wound self','Native claws')]
        b[0]['actor_template']['action_ids']=[a['source_definition_id'] for a in b[0]['action_catalog']]
        next(a for a in b[0]['action_catalog'] if a['display_name']=='Native claws')['parameters']['expected_damage']=40
        seal(b[0])
    combat,table,mid=fixture(tmp_path,[P+'BLOODLESS_DEVOURING'],bundle_transform=configure,
                             positions={OWNER:{'x':3,'y':6},ALLY:{'x':2,'y':7},FOE:{'x':4,'y':6}})
    settle(table,mid,candidate(combat,mid,'Wound self').candidate_id)
    settle(table,mid,candidate(combat,mid,'Wound',target=FOE).candidate_id,{CHOICE:None})
    combat.set_controller_mode(mid,actor_id=OWNER,controller_mode='LOCAL_AUTO')
    select_native_primary(combat,mid,'Native claws',FOE)
    result=combat.local_step(mid)
    assert result['status']=='COMMITTED',result
    e=reload(tmp_path,mid)
    paid=[ev for ev in e.events if ev.event_type=='RESOURCE_SPENT' and ev.source_definition_id==P+'BLOODLESS_DEVOURING']
    assert len(paid)==1 and paid[0].payload['amount']==1
    assert e.state.actors[OWNER].current_hp==56
