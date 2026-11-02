"""Wrestling automation at the committed table, including cold replay."""
import copy
import pytest
from combat.canonical import canonical_sha256
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, reload, settle, turn
from tests.test_auto135_wrestling import choosing

PILE = 'TAL_WRESTLING_PILEDRIVER'
TWIN = 'TAL_WRESTLING_TWIN_TIE_UP'


def prepare(bundles, *, hit=True, saved=False, twin=False):
    for b in bundles:
        b['actor_template']['saving_throws'].update(STR=-100, DEX=-100, CON=100 if saved else -100)
        if b['actor_id'] == FOE:
            for a in b['action_catalog']:
                for r in (a['parameters'].get('typed') or {}).get('effects') or []:
                    if r.get('type') == 'escape_grapple':
                        r['bonus'] = -100
        if b['actor_id'] == OWNER:
            for a in b['action_catalog']:
                t = a['parameters'].get('typed') or {}
                if a['parameters'].get('piledriver_runtime'):
                    t['numbers']['attack_bonus'] = 100 if hit else -100
            # An action-free represented Wrestler grapple setup; attacks remain real compiled ones.
            a = copy.deepcopy(next(a for a in b['action_catalog'] if a['display_name'] == 'Grapple'))
            a.update(source_definition_id='action:test.a2wrestling.grapple', display_name='Test hold', economy='NONE')
            b['action_catalog'].append(a); b['actor_template']['action_ids'].append(a['source_definition_id'])
        b.pop('bundle_sha256', None); b['bundle_sha256'] = canonical_sha256(b)


def setup(tmp_path, *, hit=True, saved=False, twin=False, ai=False):
    combat, table, mid = fixture(tmp_path, [PILE] + ([TWIN] if twin else []),
        positions={OWNER:{'x':3,'y':6}, FOE:{'x':3,'y':5}, ALLY:{'x':4,'y':6}},
        bundle_transform=lambda b: prepare(b, hit=hit, saved=saved, twin=twin), seed='A2WRESTLIN-2')
    settle(table, mid, candidate(combat, mid, 'Test hold', target=FOE).candidate_id)
    return combat, table, mid


@pytest.mark.parametrize('hit,saved', [(True,False),(True,True),(False,False)])
def test_piledriver_paid_before_roll_and_only_hit_gets_save(tmp_path, hit, saved):
    combat, table, mid = setup(tmp_path, hit=hit, saved=saved)
    before = reload(tmp_path, mid)
    focus = before.state.actors[OWNER].resources['resource:core.martial_focus']
    hp = before.state.actors[FOE].current_hp
    settle(table, mid, candidate(combat, mid, 'Piledriver: Unarmed Strike', target=FOE).candidate_id)
    e = reload(tmp_path, mid)
    assert e.state.actors[OWNER].resources['resource:core.martial_focus'] == focus-1
    rows = list(e.state.actors[FOE].conditions.values())
    assert any(c.condition_id=='condition:typed.prone' for c in rows) == hit
    stun = [c for c in rows if c.condition_id=='condition:typed.stunned']
    assert bool(stun) == (hit and not saved)
    saves = [v for v in e.events if v.event_type=='SAVE_ROLLED' and 'piledriver' in v.source_definition_id]
    assert len(saves) == int(hit)
    if hit:
        assert saves[0].payload['dc']==14
        assert e.state.actors[FOE].current_hp == hp-3
    else:
        assert e.state.actors[FOE].current_hp == hp
    paid = next(v.sequence for v in e.events if v.event_type=='RESOURCE_SPENT' and 'piledriver' in v.source_definition_id)
    rolled = next(v.sequence for v in e.events if v.event_type=='ATTACK_ROLLED' and 'piledriver' in v.source_definition_id)
    assert paid < rolled
    if stun:
        turn(table, mid, FOE); turn(table, mid, OWNER)
        assert any(c.condition_id=='condition:typed.stunned' for c in reload(tmp_path,mid).state.actors[FOE].conditions.values())
        settle(table, mid, table.state(mid)['menu']['end_turn'])
        assert not any(c.condition_id=='condition:typed.stunned' for c in reload(tmp_path,mid).state.actors[FOE].conditions.values())


def test_piledriver_not_offered_without_own_grapple(tmp_path):
    combat,table,mid=fixture(tmp_path,[PILE],foe_position={'x':3,'y':5})
    e=reload(tmp_path,mid)
    assert not any(e.action_catalog.get(c.source_definition_id) and e.action_catalog[c.source_definition_id].parameters.get('piledriver_runtime') for c in e.legal_candidates())

SECOND = 'actor:factory.worker2-ally3'
HAMMER = 'TAL_WRESTLING_HAMMERLOCK'


def paired_setup(tmp_path, *, ai=False, second_save=False, better_saves=False, both_str=False):
    def transform(bundles):
        prepare(bundles)
        for b in bundles:
            if b['actor_id'] in [FOE, SECOND] and (better_saves or both_str):
                b['actor_template']['saving_throws'].update(STR=30 if b['actor_id']==SECOND or both_str else -30,
                                                           DEX=-30 if b['actor_id']==SECOND or both_str else 30)
                b.pop('bundle_sha256',None); b['bundle_sha256']=canonical_sha256(b)
            if b['actor_id'] == SECOND and second_save:
                b['actor_template']['saving_throws'].update(STR=100, DEX=100)
                b.pop('bundle_sha256',None); b['bundle_sha256']=canonical_sha256(b)
    combat,table,mid=fixture(tmp_path,[PILE,TWIN,HAMMER,'TAL_WRESTLING_REST_HOLD'],extra_allies=1,
        positions={OWNER:{'x':3,'y':6},FOE:{'x':3,'y':5},ALLY:{'x':4,'y':6},SECOND:{'x':4,'y':5}},
        bundle_transform=transform,seed='A2WRESTLIN-2')
    combat.change_relations(mid,change={'kind':'ACTOR_RELATION','subject':OWNER,'other':SECOND,'relation':'ENEMY'},
                            expected_state_version=combat._load_session(mid).engine.state.state_version)
    if ai:
        combat.set_controller_mode(mid,actor_id=OWNER,controller_mode='LOCAL_AUTO')
    return combat,table,mid


@pytest.mark.parametrize('second_save',[False,True])
def test_twin_tie_up_separate_parts_saves_and_release(tmp_path,second_save):
    combat,table,mid=paired_setup(tmp_path,second_save=second_save)
    prompts=settle(table,mid,candidate(combat,mid,'Twin Tie-Up',target=FOE).candidate_id,
                   {'choice:needle.twin_second':SECOND})
    p=next(p for p in prompts if p['context']['reaction_source_id']=='choice:needle.twin_second')
    assert [o['id'] for o in p['choice']['options']]==[SECOND]
    e=reload(tmp_path,mid)
    holds={tid:[c for c in e.state.actors[tid].conditions.values() if c.condition_id=='condition:typed.grappled'
                and c.source_actor_id==OWNER] for tid in [FOE,SECOND]}
    assert len(holds[FOE])==1 and len(holds[SECOND])==int(not second_save)
    assert holds[FOE][0].data['grappling_part'].startswith('hand:')
    if not second_save:
        assert holds[FOE][0].data['grappling_part']!=holds[SECOND][0].data['grappling_part']
        assert holds[FOE][0].data['wrestling_twin_group']==holds[SECOND][0].data['wrestling_twin_group']
    # Release one grapple at the table; the other remains untouched.
    release=next(c for c in e.legal_candidates() if e.action_catalog.get(c.source_definition_id) and e.action_catalog[c.source_definition_id].display_name=='Release one grapple' and c.target_ids==(FOE,))
    description = next(g['description'] for g in table.state(mid)['menu']['actions']
                       if g['source_definition_id'] == release.source_definition_id)
    assert description == ('No action or resource cost: immediately end only your hold on the selected creature. '
                           'Your other grapple stays in place, as do any holds from other creatures.')
    settle(table,mid,release.candidate_id)
    e=reload(tmp_path,mid)
    assert not any(c.condition_id=='condition:typed.grappled' for c in e.state.actors[FOE].conditions.values())
    assert any(c.condition_id=='condition:typed.grappled' for c in e.state.actors[SECOND].conditions.values()) == (not second_save)


def test_twin_work_hold_applies_same_slam_to_both_after_turn_start(tmp_path):
    combat,table,mid=paired_setup(tmp_path)
    settle(table,mid,candidate(combat,mid,'Twin Tie-Up',target=FOE).candidate_id,{'choice:needle.twin_second':SECOND})
    # Establish the Hold is one target; Work the Hold begins only on a later turn.
    settle(table,mid,candidate(combat,mid,'Apply a Slam: Hammerlock',target=FOE).candidate_id)
    assert not any(c.condition_id=='condition:typed.wrestling_hold' for c in reload(tmp_path,mid).state.actors[SECOND].conditions.values())
    turn(table,mid,FOE);turn(table,mid,OWNER)
    settle(table,mid,candidate(combat,mid,'Apply a Slam: Hammerlock',target=FOE).candidate_id)
    e=reload(tmp_path,mid)
    for tid in [FOE,SECOND]:
        assert any(c.condition_id=='condition:typed.wrestling_hold' and c.data.get('hold')=='hammerlock'
                   and c.source_actor_id==OWNER for c in e.state.actors[tid].conditions.values())
    assert not any(c.condition_id=='condition:typed.wrestling_hold' for c in e.state.actors[ALLY].conditions.values())


@pytest.mark.parametrize('ai,decline',[(False,False),(False,True),(True,False)])
def test_piledriver_twin_second_target_with_ally_in_range(tmp_path,ai,decline):
    combat,table,mid=paired_setup(tmp_path,ai=ai)
    twin=candidate(combat,mid,'Twin Tie-Up',target=FOE)
    if ai:
        choosing(combat,twin.candidate_id)
    settle(table,mid,twin.candidate_id,{'choice:needle.twin_second':SECOND},auto=ai)
    if ai:
        combat.set_controller_mode(mid,actor_id=OWNER,controller_mode='MANUAL')
    settle(table,mid,candidate(combat,mid,'Rest Hold').candidate_id)
    turn(table,mid,FOE);turn(table,mid,OWNER)
    pile=candidate(combat,mid,'Piledriver: Unarmed Strike',target=FOE)
    if ai:
        combat.set_controller_mode(mid,actor_id=OWNER,controller_mode='LOCAL_AUTO')
        choosing(combat,pile.candidate_id)
    e=reload(tmp_path,mid);hp={tid:e.state.actors[tid].current_hp for tid in [FOE,SECOND,ALLY]}
    prompts=settle(table,mid,pile.candidate_id,{'choice:needle.piledriver_second':None if decline else SECOND},auto=ai)
    e=reload(tmp_path,mid)
    attacks=[v for v in e.events if v.event_type=='ATTACK_ROLLED' and 'piledriver' in v.source_definition_id]
    assert len(attacks)==(1 if decline else 2)
    assert {tid for v in attacks for tid in v.target_ids}==({FOE} if decline else {FOE,SECOND})
    assert e.state.actors[ALLY].current_hp==hp[ALLY]
    assert e.state.actors[OWNER].resources['resource:core.martial_focus']==0
    if not ai:
        p=next(p for p in prompts if p['context']['reaction_source_id']=='choice:needle.piledriver_second')
        assert [o['id'] for o in p['choice']['options']]==[SECOND]
        assert f'Piledriver: Unarmed Strike against {e.state.actors[FOE].display_name}' in p['moment']


def test_twin_escape_advantage_and_punish_slam_stays_single_target(tmp_path):
    combat,table,mid=paired_setup(tmp_path)
    settle(table,mid,candidate(combat,mid,'Twin Tie-Up',target=FOE).candidate_id,{'choice:needle.twin_second':SECOND})
    # Enter Work-the-Hold window, then the held foe attempts escape on its turn.
    turn(table,mid,FOE);turn(table,mid,OWNER);turn(table,mid,FOE)
    engine=reload(tmp_path,mid)
    hammer=next(a for a in engine.action_catalog.values() if a.owner_id==OWNER and a.display_name=='Apply a Slam: Hammerlock')
    prompts=settle(table,mid,candidate(combat,mid,'Escape grapple').candidate_id,
                   {'choice:needle.wrestling_punish':hammer.source_definition_id})
    e=reload(tmp_path,mid)
    check=next(v for v in reversed(e.events) if v.event_type=='CHECK_ROLLED' and v.actor_id==FOE)
    assert check.payload['actor']['mode']=='ADVANTAGE'
    assert check.payload['success'] is False
    assert any(p['context']['reaction_source_id']=='choice:needle.wrestling_punish' for p in prompts)
    assert any(c.condition_id=='condition:typed.wrestling_hold' for c in e.state.actors[FOE].conditions.values())
    assert not any(c.condition_id=='condition:typed.wrestling_hold' for c in e.state.actors[SECOND].conditions.values())



@pytest.mark.parametrize('iron',[False,True])
def test_piledriver_keeps_ordinary_unarmed_profile_and_remaining_extra_attacks(tmp_path,iron):
    talents=[PILE,'tianxia.path.body_refining.feature.extra_attack']
    if iron:
        talents.append('TAL_IRON_FIST_IRON_FIST_TRAINING')
    combat,table,mid=fixture(tmp_path,talents,cl=10,foe_position={'x':3,'y':5},
                            bundle_transform=prepare,seed='A2WRESTLIN-2')
    settle(table,mid,candidate(combat,mid,'Test hold',target=FOE).candidate_id)
    engine=reload(tmp_path,mid)
    pile=next(a for a in engine.action_catalog.values() if a.owner_id==OWNER and a.parameters.get('piledriver_runtime'))
    naturals=[a for a in engine.action_catalog.values() if a.owner_id==OWNER and '.natural.' in a.source_definition_id
              and not a.parameters.get('piledriver_runtime') and not (a.parameters.get('typed') or {}).get('modifier')
              and any(r.get('type')=='attack' and r.get('attack_kind')=='unarmed' for r in (a.parameters.get('typed') or {}).get('effects') or [])]
    base=max(naturals,key=lambda a:int(a.parameters.get('expected_damage') or 0))
    assert pile.parameters['typed']['weapon']==base.parameters['typed']['weapon']
    count=base.parameters['typed']['effects'][0]['count']
    assert count==2
    settle(table,mid,candidate(combat,mid,'Piledriver: Unarmed Strike',target=FOE).candidate_id)
    e=reload(tmp_path,mid)
    attacks=[v for v in e.events if v.event_type=='ATTACK_ROLLED' and 'piledriver' in v.source_definition_id]
    saves=[v for v in e.events if v.event_type=='SAVE_ROLLED' and 'piledriver' in v.source_definition_id]
    assert len(attacks)==count
    assert len(saves)==1
    assert e.state.actors[OWNER].resources['resource:core.martial_focus']==0


def test_ai_work_hold_does_not_slam_a_grappled_creature_that_became_an_ally(tmp_path):
    combat,table,mid=paired_setup(tmp_path)
    settle(table,mid,candidate(combat,mid,'Twin Tie-Up',target=FOE).candidate_id,{'choice:needle.twin_second':SECOND})
    turn(table,mid,FOE);turn(table,mid,OWNER)
    combat.change_relations(mid,change={'kind':'ACTOR_RELATION','subject':OWNER,'other':SECOND,'relation':'ALLY'},
                            expected_state_version=combat._load_session(mid).engine.state.state_version)
    combat.set_controller_mode(mid,actor_id=OWNER,controller_mode='LOCAL_AUTO')
    slam=candidate(combat,mid,'Apply a Slam: Hammerlock',target=FOE)
    choosing(combat,slam.candidate_id)
    settle(table,mid,slam.candidate_id,auto=True)
    e=reload(tmp_path,mid)
    assert any(c.condition_id=='condition:typed.wrestling_hold' for c in e.state.actors[FOE].conditions.values())
    assert not any(c.condition_id=='condition:typed.wrestling_hold' for c in e.state.actors[SECOND].conditions.values())
    assert not any(c.condition_id=='condition:typed.wrestling_hold' for c in e.state.actors[ALLY].conditions.values())


def test_twin_each_target_uses_its_chosen_save(tmp_path):
    combat,table,mid=paired_setup(tmp_path,better_saves=True)
    prompts=settle(table,mid,candidate(combat,mid,'Twin Tie-Up',target=FOE).candidate_id,
                   choices={'choice:needle.twin_second':SECOND})
    e=reload(tmp_path,mid)
    saves=[v for v in e.events if v.event_type=='SAVE_ROLLED' and TWIN in v.source_definition_id]
    assert len(saves)==2
    assert saves[0].payload['reason'].endswith(':DEX') and saves[0].payload['success']
    assert saves[1].payload['reason'].endswith(':STR') and saves[1].payload['success']
    assert {p['context']['reactor_id'] for p in prompts if p['context']['reaction_source_id']=='choice:needle.save_choice'}=={FOE,SECOND}
    assert not any(c.condition_id=='condition:typed.grappled' for tid in [FOE,SECOND] for c in e.state.actors[tid].conditions.values())


def test_ai_twin_lets_manual_defenders_choose_their_weaker_save(tmp_path):
    combat,table,mid=paired_setup(tmp_path,ai=True,both_str=True)
    twin=candidate(combat,mid,'Twin Tie-Up',target=FOE)
    choosing(combat,twin.candidate_id)
    prompts=settle(table,mid,twin.candidate_id,{'choice:needle.save_choice':'DEX'},auto=True)
    e=reload(tmp_path,mid)
    assert {p['context']['reactor_id'] for p in prompts if p['context']['reaction_source_id']=='choice:needle.save_choice'}=={FOE,SECOND}
    for tid in [FOE,SECOND]:
        assert any(c.condition_id=='condition:typed.grappled' and c.source_actor_id==OWNER for c in e.state.actors[tid].conditions.values())
    saves=[v for v in e.events if v.event_type=='SAVE_ROLLED' and TWIN in v.source_definition_id]
    assert len(saves)==2 and all(v.payload['reason'].endswith(':DEX') and not v.payload['success'] for v in saves)


@pytest.mark.parametrize('enabled', [True, False])
def test_piledriver_uses_configured_ordinary_unarmed_hit_rider(tmp_path, enabled):
    rider = 'TAL_VOID_NULLIFYING_STRIKE'
    combat, table, mid = fixture(tmp_path,
        [PILE, rider, 'tianxia.path.body_refining.feature.extra_attack'], cl=10,
        foe_position={'x':3,'y':5}, bundle_transform=prepare, seed='A2WRESTLIN-2')
    engine = reload(tmp_path, mid)
    base = next(a for a in engine.action_catalog.values() if a.owner_id == OWNER
                and a.display_name == 'Unarmed Strike' and not a.parameters['typed'].get('variant_of'))
    fields = [('option', '0'), ('payment', '0'), ('damage', 'psychic')]
    if enabled:
        fields.insert(0, ('on', 'toggle'))
    for field, value in fields:
        engine = reload(tmp_path, mid)
        action = next(a for a in engine.action_catalog.values()
                      if (a.parameters.get('attack_modifier_setting') or {}).get('family') == base.source_definition_id
                      and a.parameters['attack_modifier_setting']['modifier'] == rider
                      and a.parameters['attack_modifier_setting']['field'] == field
                      and a.parameters['attack_modifier_setting']['value'] == value)
        cid = next(c.candidate_id for c in engine.legal_candidates() if c.source_definition_id == action.source_definition_id)
        settle(table, mid, cid)
    settle(table, mid, candidate(combat, mid, 'Test hold', target=FOE).candidate_id)
    before = reload(tmp_path, mid)
    qi = before.state.actors[OWNER].resources['resource:core.qi']
    sequence = before.state.event_sequence
    settle(table, mid, candidate(combat, mid, 'Piledriver: Unarmed Strike', target=FOE).candidate_id)
    engine = reload(tmp_path, mid)
    events = [v for v in engine.events if v.sequence > sequence]
    attacks = [v for v in events if v.event_type == 'ATTACK_ROLLED' and 'piledriver' in v.source_definition_id]
    assert len(attacks) == 2
    damage = [v for v in events if v.event_type == 'DAMAGE_ROLLED' and v.payload.get('damage_label') == 'Nullifying Strike']
    payments = [v for v in events if v.event_type == 'RESOURCE_SPENT' and v.source_definition_id == rider]
    assert len(damage) == len(payments) == (2 if enabled else 0)
    assert engine.state.actors[OWNER].resources['resource:core.qi'] == qi - (4 if enabled else 0)
    assert any(c.condition_id.endswith('.reaction_denied') for c in engine.state.actors[FOE].conditions.values()) == enabled
    pile = engine.action_catalog[attacks[0].source_definition_id]
    assert pile.parameters['typed']['attack_modifier_family'] == base.source_definition_id
    assert pile.parameters['typed']['attack_modifier_loadout'] == base.parameters['typed']['attack_modifier_loadout']
