"""Berserker second pass: persisted CombatService intents and cold replay."""
import pytest
from tests.auto_worker1_support import LEFT, RIGHT, ALLY, fight, act, action_sender, reload, settle

REAPER = 'TAL_BERSERKER_REAPER_S_MOMENTUM'
WITNESS = 'actor:factory.auto111-witness'


def fixture(tmp_path, *, owned=True, foe_ac=1, left_score=50, right_hp=1000, out_of_reach=False):
    def edit(bundle):
        aid=bundle['actor_template']['entity_id']
        if aid == RIGHT:
            bundle['actor_template']['armor_class'] = foe_ac
            bundle['actor_template']['maximum_hp'] = right_hp
    c,t,m=fight(tmp_path, [REAPER] if owned else [], spheres=['tianxia.sphere.berserker'],
        left_score=left_score, ally=[], extra_witness=True, bundle_edit=edit,
        positions={LEFT:{'x':1 if out_of_reach else 3,'y':6},RIGHT:{'x':2 if out_of_reach else 4,'y':6},ALLY:{'x':1 if out_of_reach else 2,'y':7}})
    return c,t,m


def reaper_name(c,m):
    names=[a.display_name for a in reload(c,m).action_catalog.values() if a.owner_id==LEFT
           and ((a.parameters.get('typed') or {}).get('modifier') or {}).get('id')==REAPER]
    assert names, 'compiled Reaper variant required'
    return next((n for n in names if n.startswith('Batter: Bi Shou') and 'thrown' not in n),names[0])


def pick(p):
    if p['context']['reaction_source_id']=='choice:needle.weapon_hit_chain_weapon':
        ids=[o['id'] for o in p['choice']['options']]
        return [next((x for x in ids if '.weapon.' in x),ids[0])]
    if p['context']['reaction_source_id']=='choice:needle.weapon_hit_chain':
        ids=[o['id'] for o in p['choice']['options']]
        assert ALLY not in ids and LEFT not in ids
        return [WITNESS] if WITNESS in ids else ids[:1]
    return []


@pytest.mark.parametrize('ai',[False,True])
def test_reaper_hits_other_enemies_once_without_battering_allies_or_secondary(tmp_path,ai):
    c,t,m=fixture(tmp_path)
    label=reaper_name(c,m)
    before=reload(c,m)
    from combat.tabletop import attack_to_hit
    typed=next(a.parameters['typed'] for a in before.action_catalog.values() if a.display_name==label)
    assert attack_to_hit(typed)==typed['numbers']['attack_bonus']-5, "the row shows the printed -5, not the unpenalized bonus"
    assert typed['effects'][0].get('first_hit_damage') is None, "Reaper's damage is the chain, not an extra-damage fold"
    _,prompts=settle(action_sender(c,t,m,label,ai=ai,target_id=RIGHT),pick)
    e=reload(c,m)
    assert e.state.actors[RIGHT].current_hp < 1000
    assert e.state.actors[WITNESS].current_hp < 1000
    assert e.state.actors[ALLY].current_hp == 1000
    assert not any(x.condition_id.endswith('.battered') for x in e.state.actors[WITNESS].conditions.values())
    rolls=[v for v in e.events if v.event_type=='ATTACK_ROLLED' and v.actor_id==LEFT]
    assert len(rolls)==2
    assert {v.target_ids[0] for v in rolls}=={RIGHT,WITNESS}
    base=next(a.parameters['typed']['numbers']['attack_bonus'] for a in before.action_catalog.values() if a.display_name==label)
    assert all(v.payload['modifier']==base-5 for v in rolls)
    assert not any(v.event_type=='GM_RIDER' and 'Reaper' in str(v.payload) for v in e.events)


def test_reaper_chain_does_not_apply_the_standing_exertion_toggle_again(tmp_path):
    """The original Batter spends its one Exertion talent on Reaper's variant; the chained attacks are not Barters."""
    c,t,m=fight(tmp_path,[REAPER,"TAL_BERSERKER_BONE_BREAKER","TAL_BERSERKER_BELL_RINGER"],
        spheres=['tianxia.sphere.berserker'],left_score=50,ally=[],extra_witness=True,
        positions={LEFT:{'x':3,'y':6},RIGHT:{'x':4,'y':6},ALLY:{'x':2,'y':7}})
    settle(lambda a:act(t,m,'Exertion: Bell-Ringer',a),lambda p:[])
    settle(lambda a:act(t,m,reaper_name(c,m),a,target_id=RIGHT),pick)
    e=reload(c,m)
    for aid in (RIGHT,WITNESS):
        actor=e.state.actors[aid]
        assert not any(x.condition_id=='condition:typed.bell_rung' for x in actor.conditions.values())
        assert not any(x.target_field=='attack_roll' for x in actor.modifiers.values()), "no Bone-Breaker on a chained hit"


def test_brutal_strike_row_on_a_jian_shows_and_rolls_minus_five_and_plus_ten(tmp_path):
    """The owner's row: Batter: Jian (Straight Sword) + Brutal Strike must read +4 / 1d10+15, not +9 / 1d10+5."""
    from combat.tabletop import attack_to_hit, damage_text
    jian={"items":[{"item_id":"tianxia.mortal.weapon.jian","name":"Jian (Straight Sword)","quantity":1}]}
    def proficient(doc, aid):
        if aid==LEFT:  # Body Refining carries martial-weapon proficiency, so +5 ability and +4 PB match the owner's +9
            doc.setdefault('path_and_subpath',{})['path_record_ids']=['tianxia.path.body_refining']
    def soft_target(bundle):
        if bundle['actor_template']['entity_id']==RIGHT:
            bundle['actor_template']['armor_class']=1
    c,t,m=fight(tmp_path,["TAL_BERSERKER_BRUTAL_STRIKE"],spheres=['tianxia.sphere.berserker'],
        left_score=20,left_pb=4,left_kit=jian,ally=[],sheet_edit=proficient,bundle_edit=soft_target)
    catalog=reload(c,m).action_catalog.values()
    row=next(a for a in catalog if a.display_name.startswith('Batter: Jian') and a.display_name.endswith('+ Brutal Strike'))
    typed=row.parameters['typed']
    assert attack_to_hit(typed)==4, f"{row.display_name} shows {attack_to_hit(typed)}, not the printed +4"
    assert damage_text(typed,5)=='1d10+15 piercing', f"{row.display_name} shows {damage_text(typed,5)}, not 1d10+15"
    settle(lambda a: act(t,m,row.display_name,a,target_id=RIGHT), lambda p: [])
    events=reload(c,m).events
    attack=next(v for v in events if v.event_type=='ATTACK_ROLLED')
    assert attack.payload['expression']=='1d20+4', f"the fight rolls {attack.payload['expression']}, not the shown +4"
    damage=next(v for v in events if v.event_type=='DAMAGE_ROLLED')
    assert damage.payload['expression']=='1d10+15', f"the +10 is in the one weapon damage roll, not a second packet: {damage.payload}"


def test_brutal_strike_on_a_rest_of_the_attack_row_folds_only_its_first_roll_and_first_hit(tmp_path):
    """The printed "+ Brutal Strike" variant also exists on the rest-of-the-Attack copy; Extra Attack does not make
    the penalty or the +10 apply to every swing."""
    from combat.tabletop import attack_to_hit, damage_text
    def soft_target(bundle):
        if bundle['actor_template']['entity_id']==RIGHT:
            bundle['actor_template']['armor_class']=1
    c,t,m=fight(tmp_path,["TAL_BERSERKER_BRUTAL_STRIKE","tianxia.path.body_refining.feature.extra_attack"],
        spheres=['tianxia.sphere.berserker'],ally=[],bundle_edit=soft_target)
    rows=[a for a in reload(c,m).action_catalog.values() if a.display_name.endswith('+ Brutal Strike')]
    assert rows, 'the rest-of-the-Attack copy keeps its own Brutal Strike variant'
    for row in rows:
        attack=next(e for e in row.parameters['typed']['effects'] if e.get('type')=='attack')
        assert attack['first_roll_bonus']==-5, 'the Batter roll carries the printed -5'
        assert attack.get('first_hit_damage')==10, 'the +10 is on record once, for the first hit'
        assert attack_to_hit(row.parameters['typed'])==row.parameters['typed']['numbers']['attack_bonus']-5
    row=next(a for a in reload(c,m).action_catalog.values()
             if a.display_name.endswith('+ Brutal Strike') and 'Bi Shou' in a.display_name and 'thrown' not in a.display_name)
    attack=next(e for e in row.parameters['typed']['effects'] if e.get('type')=='attack')
    assert attack.get('count')==3, 'the rest of the Attack action is part of this one variant'
    settle(lambda a: act(t,m,row.display_name,a,target_id=RIGHT), lambda p: [])
    events=reload(c,m).events
    rolls=[v for v in events if v.event_type=='ATTACK_ROLLED' and v.actor_id==LEFT]
    assert len(rolls)==3
    base=row.parameters['typed']['numbers']['attack_bonus']
    assert rolls[0].payload['modifier']==base-5, 'only the Batter roll takes Brutal Strike\'s penalty'
    assert all(v.payload['modifier']==base for v in rolls[1:]), 'the rest-of-the-Attack swings do not'
    damages=[v for v in events if v.event_type=='DAMAGE_ROLLED' and v.actor_id==LEFT]
    assert len(damages)==3
    assert damages[0].payload['expression']=='1d4+12', 'the first hit owns the +10'
    assert all(v.payload['expression']=='1d4+2' for v in damages[1:]), 'later hits do not repeat it'


def test_reaper_missed_initial_attack_grants_no_chain(tmp_path):
    c,t,m=fixture(tmp_path,foe_ac=1000)
    _,prompts=settle(lambda a:act(t,m,reaper_name(c,m),a,target_id=RIGHT),pick)
    e=reload(c,m)
    assert e.state.actors[WITNESS].current_hp==1000
    assert not any(p['context']['reaction_source_id']=='choice:needle.weapon_hit_chain' for p in prompts)


def test_reaper_player_can_decline_without_spending_extra_economy(tmp_path):
    c,t,m=fixture(tmp_path)
    settle(lambda a:act(t,m,reaper_name(c,m),a,target_id=RIGHT),lambda p:[])
    e=reload(c,m)
    assert e.state.actors[WITNESS].current_hp==1000
    assert e.state.actors[LEFT].bonus_action_available


def test_actor_without_reaper_gets_no_chain(tmp_path):
    c,t,m=fixture(tmp_path,owned=False)
    e=reload(c,m)
    label=next(a.display_name for a in e.action_catalog.values() if a.owner_id==LEFT and a.display_name.startswith('Batter:'))
    settle(lambda a:act(t,m,label,a,target_id=RIGHT),pick)
    assert reload(c,m).state.actors[WITNESS].current_hp==1000


def test_reaper_secondary_miss_stops_chain_without_retry(tmp_path):
    c,t,m=fixture(tmp_path,left_score=30)
    settle(lambda a:act(t,m,reaper_name(c,m),a,target_id=RIGHT),pick)
    e=reload(c,m)
    rolls=[v for v in e.events if v.event_type=='ATTACK_ROLLED' and v.actor_id==LEFT]
    assert len(rolls)==2 and not rolls[-1].payload['provisional_hit']
    assert e.state.actors[WITNESS].current_hp==1000


def test_reaper_out_of_reach_enemy_never_offered(tmp_path):
    c,t,m=fixture(tmp_path,out_of_reach=True)
    _,prompts=settle(lambda a:act(t,m,reaper_name(c,m),a,target_id=RIGHT),pick)
    assert reload(c,m).state.actors[WITNESS].current_hp==1000
    assert not any(p['context']['reaction_source_id']=='choice:needle.weapon_hit_chain' for p in prompts)


def test_reaper_lethal_first_hit_still_continues(tmp_path):
    c,t,m=fixture(tmp_path,right_hp=1)
    settle(lambda a:act(t,m,reaper_name(c,m),a,target_id=RIGHT),pick)
    e=reload(c,m)
    assert e.state.actors[RIGHT].current_hp==0
    assert e.state.actors[WITNESS].current_hp<1000

BELL = 'TAL_BERSERKER_BELL_RINGER'


@pytest.mark.parametrize('beat_down',[False,True])
@pytest.mark.parametrize('legacy',[False,True])
def test_bell_ringer_own_concentration_check_int_checks_and_ordinary_con_save(tmp_path,beat_down,legacy):
    from copy import deepcopy
    from tests.auto_worker1_support import turn
    def edit(bundle):
        if bundle['actor_template']['entity_id']==LEFT and legacy:
            for row in bundle['typed_passives']:
                row.pop('bell_runtime',None)
        if bundle['actor_template']['entity_id']==RIGHT:
            cause=next(a for a in bundle['action_catalog'] if a['display_name']=='Cause')
            cause['parameters']['typed']['duration']={'kind':'one_minute','concentration':True}
            for ability in ('INT','STR','CON'):
                probe=deepcopy(cause)
                probe.update(source_definition_id='action:test.bell.'+ability,display_name='Probe '+ability,
                             target_kind='HOSTILE_ENTITY' if ability!='CON' else 'SELF')
                probe['parameters']['typed']['duration']={'kind':'instant'}
                probe['parameters']['typed']['effects']=[{'type':'contest_against','actor_check':{'kind':'check','ability':ability},
                    'target_check':{'kind':'dc','dc':10}}] if ability!='CON' else [
                    {'type':'save','ability':'con','dc':10,'applies_to':'self','on_fail':[],'on_success':[]}]
                bundle['action_catalog'].append(probe)
                bundle['actor_template']['action_ids'].append(probe['source_definition_id'])
    c,t,m=fight(tmp_path,[BELL,*(['TAL_BERSERKER_BEAT_DOWN'] if beat_down else [])],
        spheres=['tianxia.sphere.berserker'], left_score=50,bundle_edit=edit,
        cause=[{'type':'state','name':'test_concentration','duration':'one_minute'}],cause_target='SELF')
    turn(t,m,RIGHT)
    settle(lambda a:act(t,m,'Cause',a),lambda p:[])
    turn(t,m,LEFT)
    settle(lambda a:act(t,m,'Batter',a,target_id=RIGHT),lambda p:[])
    e=reload(c,m)
    conc=[v for v in e.events if v.event_type=='SAVE_ROLLED' and 'concentration' in v.source_definition_id]
    assert conc, [v.source_definition_id for v in e.events if v.event_type=='SAVE_ROLLED']
    assert conc[-1].payload['mode']==('NORMAL' if legacy else 'DISADVANTAGE')
    rows=[x for x in e.state.actors[RIGHT].conditions.values() if x.condition_id.endswith('.bell_rung')]
    assert len(rows)==1
    # On the defender's next turn the printed disadvantage still applies.
    turn(t,m,RIGHT)
    for ability in ('INT','STR','CON'):
        settle(lambda a:act(t,m,'Probe '+ability,a,target_id=LEFT if ability!='CON' else None),lambda p:[])
    e=reload(c,m)
    probes=[v for v in e.events if v.event_type in ('CHECK_ROLLED','SAVE_ROLLED') and 'action:test.bell.' in v.source_definition_id]
    assert len(probes)==3
    int_roll=next(v for v in probes if v.source_definition_id.endswith('INT'))
    assert int_roll.payload['actor']['mode']==('NORMAL' if legacy else 'DISADVANTAGE')
    assert next(v for v in probes if v.source_definition_id.endswith('STR')).payload['actor']['mode']=='NORMAL'
    assert next(v for v in probes if v.source_definition_id.endswith('CON')).payload['mode']=='NORMAL'
    turn(t,m,LEFT)
    e=reload(c,m)
    assert any(x.condition_id.endswith('.bell_rung') for x in e.state.actors[RIGHT].conditions.values())==beat_down
    if beat_down:
        turn(t,m,RIGHT);turn(t,m,LEFT)
        assert not any(x.condition_id.endswith('.bell_rung') for x in reload(c,m).state.actors[RIGHT].conditions.values())
    assert any(v.event_type=='GM_RIDER' and 'Bell-Ringer:' in str(v.payload) for v in e.events)==legacy


@pytest.mark.parametrize('owned',[False,True])
def test_beat_down_battered_expires_on_second_owner_turn_end(tmp_path,owned):
    from tests.auto_worker1_support import turn
    c,t,m=fight(tmp_path,['TAL_BERSERKER_BEAT_DOWN'] if owned else [],
        spheres=['tianxia.sphere.berserker'],left_score=50)
    settle(lambda a:act(t,m,'Batter',a,target_id=RIGHT),lambda p:[])
    assert any(x.condition_id.endswith('.battered') for x in reload(c,m).state.actors[RIGHT].conditions.values())
    turn(t,m,RIGHT);turn(t,m,LEFT)
    assert any(x.condition_id.endswith('.battered') for x in reload(c,m).state.actors[RIGHT].conditions.values())
    turn(t,m,RIGHT)
    assert any(x.condition_id.endswith('.battered') for x in reload(c,m).state.actors[RIGHT].conditions.values())==owned
    if owned:
        turn(t,m,LEFT);turn(t,m,RIGHT)
        assert not any(x.condition_id.endswith('.battered') for x in reload(c,m).state.actors[RIGHT].conditions.values())


def test_reaper_unperceived_enemy_never_offered_to_ai(tmp_path):
    invisible={'type':'condition','condition':'invisible','applies_to':'target','duration':'one_minute'}
    c,t,m=fight(tmp_path,[REAPER],spheres=['tianxia.sphere.berserker'],left_score=50,
        prepare=[invisible],ally=[],extra_witness=True, positions={LEFT:{'x':3,'y':6},RIGHT:{'x':4,'y':6},ALLY:{'x':2,'y':6}})
    settle(lambda a:act(t,m,'Prepare',a,target_id=WITNESS),lambda p:[])
    _,prompts=settle(action_sender(c,t,m,reaper_name(c,m),ai=True,target_id=RIGHT),pick)
    assert reload(c,m).state.actors[WITNESS].current_hp==1000
    assert not any(p['context']['reaction_source_id']=='choice:needle.weapon_hit_chain' for p in prompts)


def test_reaper_unstamped_sealed_variant_stays_inert(tmp_path):
    from combat.ext.rider_helpers import effect_rows
    def old(bundle):
        if bundle['actor_template']['entity_id']==LEFT:
            for a in bundle['action_catalog']:
                typed=a['parameters'].get('typed') or {}
                for row in effect_rows(typed.get('effects')):
                    if row.get('type')=='attack':
                        row['on_hit']=[r for r in row.get('on_hit',[]) if r.get('type')!='weapon_hit_chain']
    c,t,m=fight(tmp_path,[REAPER],spheres=['tianxia.sphere.berserker'],left_score=50,
        ally=[],extra_witness=True,bundle_edit=old, positions={LEFT:{'x':3,'y':6},RIGHT:{'x':4,'y':6},ALLY:{'x':2,'y':6}})
    settle(lambda a:act(t,m,reaper_name(c,m),a,target_id=RIGHT),pick)
    assert reload(c,m).state.actors[WITNESS].current_hp==1000


def test_reaper_continues_past_second_enemy_and_never_repeats(tmp_path,monkeypatch):
    import json
    from combat.gate5_service import CombatService
    from combat.canonical import canonical_sha256
    extra='actor:factory.reaper-third'
    original=CombatService._finish_factory_match
    def roster(self,bundles,ids,teams,spots,*args,**kwargs):
        # Extend synthetic genesis, never a running engine or retained save.
        witness=next(b for b in bundles if b['actor_id']==WITNESS)
        clone=json.loads(json.dumps(witness).replace(WITNESS,extra).replace('.3efc46d95f', '.reaperthird'))
        clone['actor_template']['armor_class']=1
        clone.pop('bundle_sha256',None)
        clone['bundle_sha256']=canonical_sha256(clone)
        return original(self,[*bundles,clone],[*ids,extra],{**teams,extra:'team:opponents'},
                        {**spots,extra:{'x':4,'y':7}},*args,**kwargs)
    monkeypatch.setattr(CombatService,'_finish_factory_match',roster)
    c,t,m=fixture(tmp_path)
    settle(lambda a:act(t,m,reaper_name(c,m),a,target_id=RIGHT),pick)
    e=reload(c,m)
    rolls=[v for v in e.events if v.event_type=='ATTACK_ROLLED' and v.actor_id==LEFT]
    assert len(rolls)==3
    assert {v.target_ids[0] for v in rolls}=={RIGHT,WITNESS,extra}
    assert all(e.state.actors[x].current_hp<1000 for x in (RIGHT,WITNESS,extra))
    assert e.state.actors[ALLY].current_hp==1000


def test_reaper_player_can_choose_a_different_readied_implement(tmp_path):
    c,t,m=fixture(tmp_path)
    e=reload(c,m)
    root=next(a.display_name for a in e.action_catalog.values() if a.owner_id==LEFT
              and a.display_name.startswith('Batter + Reaper'))
    _,prompts=settle(lambda a:act(t,m,root,a,target_id=RIGHT),pick)
    e=reload(c,m)
    rolls=[v for v in e.events if v.event_type=='ATTACK_ROLLED' and v.actor_id==LEFT]
    assert len(rolls)==2
    # The synthetic unproficient dagger has four less to hit than the
    # proficient Unarmed Strike; both take their own printed -5.
    assert rolls[0].payload['modifier']-rolls[1].payload['modifier']==4
    assert e.state.actors[WITNESS].current_hp<1000
    assert any(p['context']['reaction_source_id']=='choice:needle.weapon_hit_chain_weapon' for p in prompts)


@pytest.mark.parametrize('active',[False,True])
@pytest.mark.parametrize('resisted',[False,True])
def test_berserk_owned_adrenaline_reduces_by_pb_before_resistance(tmp_path,active,resisted):
    from tests.auto_worker1_support import turn
    resist={'type':'resistance','applies_to':'self','damage_types':['bludgeoning'],'duration':'one_minute'}
    c,t,m=fight(tmp_path,['TAL_BERSERKER_BERSERK'],spheres=['tianxia.sphere.berserker'],
        prepare=[resist],prepare_target='SELF',
        cause=[{'type':'damage','flat':20,'damage_types':['bludgeoning'],'applies_to':'target'}])
    if resisted:
        settle(lambda a:act(t,m,'Prepare',a),lambda p:[])
    if active:
        settle(lambda a:act(t,m,'Adrenaline: Berserk',a),lambda p:[])
    turn(t,m,RIGHT)
    settle(lambda a:act(t,m,'Cause',a,target_id=LEFT),lambda p:[])
    e=reload(c,m)
    expected=(20-(4 if active else 0))//(2 if resisted else 1)
    assert e.state.actors[LEFT].current_hp==1000-expected
    assert not any(v.event_type=='GM_RIDER' and 'Berserk' in str(v.payload) for v in e.events)


HEAVEN_CRUSHING = 'TAL_BERSERKER_HEAVEN_CRUSHING_EXERTION'


def _concentrating_foe_edit(bundle):
    from tests.auto_worker1_support import RIGHT as _R
    if bundle['actor_template']['entity_id'] == _R:
        cause = next(a for a in bundle['action_catalog'] if a['display_name'] == 'Cause')
        cause['parameters']['typed']['duration'] = {'kind': 'one_minute', 'concentration': True}


def _pick_bell_ringer(prompt):
    """Answer the Exertion menu with Bell-Ringer alone, and nothing else."""
    if 'exertion_set' in prompt['context']['reaction_source_id']:
        return [o['id'] for o in prompt['choice']['options'] if o['id'] == 'bell_ringer']
    return []


def test_bell_ringer_disadvantages_the_save_its_deferred_on_hit_damage_causes(tmp_path):
    """Bell-Ringer's printed Disadvantage must reach the save its OWN hit damage causes.

    Heaven-Crushing Exertion's extra Force damage is a printed on-hit row against an already
    Battered target, so it commits after that attack's scope has closed -- not as part of the
    attack roll. This pins that the target concentrating through THAT damage still makes the save
    with the printed Disadvantage, rather than the bell landing only after the save it was supposed
    to have changed. CombatService intents and a cold reload, like every assertion here.
    """
    from tests.auto_worker1_support import turn
    c, t, m = fight(tmp_path, [BELL, HEAVEN_CRUSHING], spheres=['tianxia.sphere.berserker'],
        left_score=50, left_attack_bonus=20, bundle_edit=_concentrating_foe_edit,
        cause=[{'type': 'state', 'name': 'test_concentration', 'duration': 'one_minute'}],
        cause_target='SELF')
    turn(t, m, RIGHT)
    settle(lambda a: act(t, m, 'Cause', a), lambda p: [])
    turn(t, m, LEFT)
    settle(lambda a: act(t, m, 'Batter', a, target_id=RIGHT), lambda p: [])
    e = reload(c, m)
    assert any(x.condition_id.endswith('.battered') for x in e.state.actors[RIGHT].conditions.values()), \
        'the target must already be Battered for the printed extra Force damage to fire'
    turn(t, m, RIGHT)
    settle(lambda a: act(t, m, 'Cause', a), lambda p: [])
    turn(t, m, LEFT)
    settle(lambda a: act(t, m, 'Heaven-Crushing Exertion', a, target_id=RIGHT), _pick_bell_ringer)

    e = reload(c, m)
    hits = [v for v in e.events if v.event_type == 'ATTACK_ROLLED' and HEAVEN_CRUSHING in v.source_definition_id]
    assert hits, 'the deferred-damage attack resolved'
    after = [v for v in e.events if v.sequence > hits[-1].sequence]
    damage = next((v for v in after if v.event_type == 'DAMAGE_COMMITTED' and RIGHT in v.target_ids
                   and int(v.payload.get('hp_damage') or 0) > 0), None)
    assert damage is not None, 'the printed extra Force damage landed'
    save = next((v for v in after if v.sequence > damage.sequence and v.event_type == 'SAVE_ROLLED'
                 and 'concentration' in v.source_definition_id), None)
    assert save is not None, 'that damage asked the defender for a Concentration save'
    assert save.payload['mode'] == 'DISADVANTAGE', \
        f'the bell must ring before this save, not after it: {save.payload}'
    assert any(x.condition_id.endswith('.bell_rung') for x in e.state.actors[RIGHT].conditions.values())


def _chain_prompts(prompts):
    return [p for p in prompts if p['context']['reaction_source_id'].startswith('choice:needle.weapon_hit_chain')]


def test_reaper_prompts_name_the_attack_that_granted_the_chain_and_the_creature_it_hit(tmp_path):
    """Every Reaper question says which hit opened the chain and who it struck (checklist 9/13).

    The follow-up recipient is not chosen yet, so the creature named is the one the triggering hit
    struck -- never the enemy about to be picked. This is the manual transport, which is the one that
    presents a question at all; an AI fighter answers for itself and raises no prompt to read (the AI
    turn of the Reaper test above covers that it still resolves and stays inside what it perceives).
    """
    c, t, m = fixture(tmp_path)
    label = reaper_name(c, m)
    e0 = reload(c, m)
    foe = e0.state.actors[RIGHT].display_name
    striker = e0.state.actors[LEFT].display_name
    recipient = e0.state.actors[WITNESS].display_name
    _, prompts = settle(action_sender(c, t, m, label, target_id=RIGHT), pick)
    asked = _chain_prompts(prompts)
    assert asked, 'the chain asked which enemy to follow up on'
    for prompt in asked:
        assert prompt['action'] == label, f'the question names the attack that granted it: {prompt}'
        assert prompt['affected'] == foe, f'and the creature that attack struck: {prompt}'
        assert prompt['trigger_actor'] == striker, f'and who struck it: {prompt}'
        # The recipient is still being chosen, so it must not be named as the creature affected.
        assert recipient not in (prompt['affected'], prompt['by']), \
            f'the not-yet-chosen recipient is not the creature this question is about: {prompt}'


def test_reaper_prompt_quotes_the_markers_own_penalty_not_a_typed_in_number(tmp_path):
    """The advertised penalty is the marker's own, so the text can never describe a different one.

    The marker is rewritten to -2 here: the follow-up attack's actual roll AND what the table is told
    must both follow it. A number typed into the prompt instead would still say -5 and would be
    describing a penalty the follow-up does not take.
    """
    from combat.ext.rider_helpers import effect_rows

    def edit(bundle):
        if bundle['actor_template']['entity_id'] == LEFT:
            for entry in bundle['action_catalog']:
                typed = entry['parameters'].get('typed') or {}
                for row in effect_rows(typed.get('effects')):
                    if row.get('type') == 'weapon_hit_chain' and row.get('attack_bonus') == -5:
                        row['attack_bonus'] = -2
    c, t, m = fight(tmp_path, [REAPER], spheres=['tianxia.sphere.berserker'], left_score=50,
        ally=[], extra_witness=True, bundle_edit=edit,
        positions={LEFT: {'x': 3, 'y': 6}, RIGHT: {'x': 4, 'y': 6}, ALLY: {'x': 2, 'y': 7}})
    label = reaper_name(c, m)
    before = reload(c, m)
    base = next(a.parameters['typed']['numbers']['attack_bonus']
                for a in before.action_catalog.values() if a.display_name == label)
    _, prompts = settle(action_sender(c, t, m, label, target_id=RIGHT), pick)
    asked = _chain_prompts(prompts)
    assert asked, 'the chain asked a question'
    for prompt in asked:
        assert 'at -2' in prompt['moment'], f'the prompt quotes the marker\'s own -2: {prompt["moment"]!r}'
        assert '-5' not in prompt['moment'], f'and never the -5 it no longer takes: {prompt["moment"]!r}'
    e = reload(c, m)
    rolls = [v for v in e.events if v.event_type == 'ATTACK_ROLLED' and v.actor_id == LEFT]
    assert len(rolls) == 2
    # The chain's own first hit keeps the -5 its compiled "Batter + Reaper" variant bakes in; the
    # follow-up this chain grants reads the marker, so it is the follow-up that moved to -2.
    assert rolls[-1].payload['modifier'] == base - 2, 'and the follow-up attack really took that -2'
    assert rolls[0].payload['modifier'] == base - 5, 'while the first hit kept its own compiled -5'
