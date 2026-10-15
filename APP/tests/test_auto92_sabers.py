"""Saber size, paid hit/save outcomes and opportunity-only line protection."""
import pytest
from combat.gate2_runtime_models import Position
from combat.typed_executor import condition_rules, mark_condition_id
from tests.auto_worker1_support import LEFT, RIGHT, fight, act, reload, action_sender
from tests.test_auto42_stars import turn, cell_send
from tests.test_auto45_metal import settle
from tests.test_auto62_destruction import triple_fight, OTHER, PASSAGE_ALLY, cell_sender
P='tianxia.talent.sabers.'
DAO={'items':[{'item_id':'tianxia.mortal.weapon.dao','name':'Dao','quantity':1}]}

@pytest.mark.parametrize('ai',[False,True])
def test_infantry_road_denies_only_opportunity_and_asks_chosen_allies(tmp_path,ai):
    c,t,m=triple_fight(tmp_path,[P+'thousand_saber_infantry_road'],third_ally=True)
    def pick(p):
        return [OTHER] if p['context']['reaction_source_id']=='choice:needle.sabers_passage_allies' else [RIGHT]
    _,prompts=settle(cell_sender(c,t,m,'Thousand-Saber Infantry Road',(8,6),ai),pick)
    e=reload(c,m);f=e.state.actors[RIGHT];ally=e.state.actors[OTHER]
    assert f.current_hp<1000 and ally.current_hp==1000
    assert not any(r.get('no_reactions') for r in condition_rules(f))
    assert not any(r.get('no_reactions') for r in condition_rules(ally))
    held=next(x for x in f.conditions.values() if x.condition_id.endswith('.no_opportunity_attacks'))
    passage=next(x for x in f.conditions.values() if x.condition_id.endswith('.cone_passage'))
    assert passage.data['allies']==[OTHER]
    assert 'end' in held.expires_on.lower()
    assert e.state.actors[LEFT].resources['resource:core.qi']==92
    if not ai:assert any('No extra cost' in str(p) and 'allies' in str(p) for p in prompts)
    if ai:c.set_controller_mode(m,actor_id=LEFT,controller_mode='MANUAL')
    turn(t,m,RIGHT)
    # Its own turn starts without releasing the ban; the actual end releases it.
    assert any(x.condition_id.endswith('.no_opportunity_attacks') for x in reload(c,m).state.actors[RIGHT].conditions.values())
    turn(t,m,OTHER)
    assert not any(x.condition_id.endswith('.no_opportunity_attacks') for x in reload(c,m).state.actors[RIGHT].conditions.values())


@pytest.mark.parametrize('case',['push','prone','success','decline','miss','no_move','huge','unowned','legacy'])
def test_battleline_only_pays_after_a_qualified_hit_and_final_save(tmp_path,case,ai=False,resource="Qi"):
    def size(bundle):
        if case=='huge' and bundle['actor_template']['entity_id']==RIGHT:
            bundle['actor_template']['size_category']='Huge'
        if case=='legacy':
            bundle['typed_passives']=[r for r in bundle.get('typed_passives',[]) if r.get('kind')!='battleline_shove_cut_v2']
    owned=[P+'forward_cut']+([] if case=='unowned' else [P+'battleline_shove_cut'])
    c,t,m=fight(tmp_path,owned,left_resource=resource,left_kit=DAO,positions={LEFT:{'x':2 if case=='no_move' else 1,'y':1},RIGHT:{'x':4,'y':1}},
        right_score=214 if case=='success' else 14,left_attack_bonus=-100 if case=='miss' else 100,bundle_edit=size,
        prepare_target='SELF')
    # Battleline requires movement, not a teleport. Commit the actual walk.
    state = t.state(m); menu = state['menu']
    move = next(o for o in menu['moves'] if o.get('destination') == {'x':3,'y':1})
    settle(lambda answers: t.act(m, move['candidate_id'], menu['decision_id'], menu['state_version'],
                                state['last_sequence'], answers))
    def pick(p):
        src=p['context']['reaction_source_id']
        return [] if case=='decline' and src.startswith('choice:paid_option.') else ['prone'] if src=='choice:needle.battleline_outcome' and case=='prone' else ['push'] if src=='choice:needle.battleline_outcome' else ['0']
    _,prompts=settle(action_sender(c,t,m,'Forward Cut',ai=ai,target_id=RIGHT),pick)
    e=reload(c,m);f=e.state.actors[RIGHT]
    paid=case in ('push','prone','success')
    assert e.state.actors[LEFT].resources['resource:core.'+resource.lower()]==(99 if paid else 100)
    assert f.position.x==(6 if case=='push' else 5 if case=='success' else 4)
    assert any(x.condition_id.endswith('.prone') for x in f.conditions.values())==(case=='prone')
    saves=[x for x in e.events if x.event_type=='SAVE_ROLLED']
    assert bool(saves)==paid
    if case=='miss':assert f.current_hp==1000
    if paid and not ai:assert any(p['context']['reaction_source_id'].startswith('choice:paid_option.') for p in prompts)


@pytest.mark.parametrize('target_size',['Large','Huge'])
def test_horse_arc_absolute_large_limit_does_not_scale_with_large_caster(tmp_path,target_size,legacy=False):
    def sizes(bundle):
        bundle['actor_template']['size_category']='Huge' if bundle['actor_template']['entity_id']==LEFT else target_size
        if legacy:
            for a in bundle['action_catalog']:
                for e in a.get('parameters',{}).get('typed',{}).get('effects',[]):
                    for part in e.get('on_fail',[]):
                        if part.get('type')=='if_size_at_most':part.pop('max_size',None);part['larger']=1
    c,t,m=fight(tmp_path,[P+'horse_cutting_arc'],bundle_edit=sizes,
        positions={LEFT:{'x':1,'y':1},RIGHT:{'x':6,'y':1}})
    def pick(p):return ['Knocked Prone']
    _,prompts=settle(cell_send(t,m,'Horse-Cutting Arc',(7,1)),pick)
    e=reload(c,m);f=e.state.actors[RIGHT]
    assert f.current_hp<1000
    assert any(x.condition_id.endswith('.prone') for x in f.conditions.values())==(target_size=='Large' or legacy)
    assert bool(prompts)==(target_size=='Large' or legacy)
    assert e.state.actors[LEFT].resources['resource:core.qi']==96


@pytest.mark.parametrize('case',['push','success','miss'])
def test_battleline_automatic_choices_use_actual_native_payments(tmp_path,case):
    test_battleline_only_pays_after_a_qualified_hit_and_final_save(tmp_path,case,ai=True)


@pytest.mark.parametrize('case',['accept','decline','miss','legacy'])
def test_ten_step_hit_cost_and_recipient_next_end_expiry(tmp_path,case):
    def old(bundle):
        if case=='legacy':bundle['typed_passives']=[r for r in bundle.get('typed_passives',[]) if r.get('kind')!='ten_step_pursuit_v2']
    c,t,m=fight(tmp_path,[P+'ten_step_pursuit_doctrine'],bundle_edit=old,
        prepare_source=P+'red_trail_pursuit',prepare_attack_bonus=-100 if case=='miss' else 100,
        prepare=[{'type':'attack','attack_kind':'cultivation_melee','count':1,'on_hit':[{'type':'damage','flat':2,'damage_types':['slashing'],'applies_to':'target'}]}])
    settle(lambda a:act(t,m,'Prepare',a,target_id=RIGHT),lambda p:[] if case=='decline' else ['0'])
    e=reload(c,m);assert e._effective_speed(e.state.actors[RIGHT])==(20 if case=='accept' else 30)
    assert e.state.actors[LEFT].resources['resource:core.qi']==(98 if case=='accept' else 100)
    if case=='accept':
        turn(t,m,RIGHT);assert reload(c,m)._effective_speed(reload(c,m).state.actors[RIGHT])==20
        turn(t,m,LEFT);e=reload(c,m);assert e._effective_speed(e.state.actors[RIGHT])==30


def test_secret_manuals_heading_does_not_cast_four_unselected_manuals(tmp_path):
    c,t,m=fight(tmp_path,[P+'secret_saber_manuals'])
    assert not any('Secret Saber Manuals' in g['label'] for g in t.state(m)['menu']['actions'])
    e=reload(c,m);assert e.state.actors[LEFT].resources['resource:core.qi']==100


def test_battleline_uses_the_sealed_resonance_cp_pool(tmp_path):
    test_battleline_only_pays_after_a_qualified_hit_and_final_save(tmp_path,'push',resource='Resonance')


def test_infantry_passage_asks_once_for_two_actual_failed_recipients(tmp_path):
    c,t,m=triple_fight(tmp_path,[P+'thousand_saber_infantry_road'],fourth_ally=True)
    def pick(p):
        return [PASSAGE_ALLY] if p['context']['reaction_source_id']=='choice:needle.sabers_passage_allies' else [RIGHT,OTHER]
    _,prompts=settle(cell_send(t,m,'Thousand-Saber Infantry Road',(8,5)),pick)
    e=reload(c,m)
    assert len([p for p in prompts if p['context']['reaction_source_id']=='choice:needle.sabers_passage_allies'])==1
    for aid in (RIGHT,OTHER):
        assert e.state.actors[aid].current_hp<1000
        p=next(x for x in e.state.actors[aid].conditions.values() if x.condition_id.endswith('.cone_passage'))
        assert p.data['allies']==[PASSAGE_ALLY]
    assert e.state.actors[PASSAGE_ALLY].current_hp == 1000


def test_legacy_size_gate_preserves_relative_saved_behavior(tmp_path):
    test_horse_arc_absolute_large_limit_does_not_scale_with_large_caster(tmp_path,'Huge',legacy=True)


@pytest.mark.parametrize('grown',[True,False])
def test_horse_arc_absolute_limit_reads_the_target_size_it_has_right_now(tmp_path,grown):
    """"Large or smaller" is the creature's current size, so a target grown to Huge by a real, saved size_change
    (commit + reload) is outside the cap even though its sheet still says Medium, and an ungrown Medium target
    is still inside it. dynamic_size.current_category is that reading. Both cases run: the ungrown half is the
    control that shows the gate is the size and not the growth."""
    c,t,m=fight(tmp_path,[P+'horse_cutting_arc'],
        cause=[{'type':'size_change','size':'Huge','duration':'one_minute'}] if grown else [],
        cause_name='Grow',positions={LEFT:{'x':1,'y':1},RIGHT:{'x':6,'y':1}})
    turn(t,m,RIGHT)
    if grown:
        settle(action_sender(c,t,m,'Grow'))
    turn(t,m,LEFT)
    e=reload(c,m);f=e.state.actors[RIGHT]
    assert (f.transformed_size_category=='Huge')==grown, 'the growth condition is a saved, reloaded one'
    def arc(answers):
        state=t.state(m)
        menu=state['menu']
        cid=next(o['candidate_id'] for g in menu['actions'] if g['label']=='Horse-Cutting Arc' for o in g['options']
                 if o.get('destination',{}).get('y')==f.position.y and o['destination']['x']>=f.position.x)
        return t.act(m,cid,menu['decision_id'],menu['state_version'],state['last_sequence'],answers)
    def pick(p):
        options=[o['id'] for o in (p.get('choice') or {}).get('options',[])]
        return ['Knocked Prone'] if 'Knocked Prone' in options else options[:1]
    _,prompts=settle(arc,pick)
    e=reload(c,m);f=e.state.actors[RIGHT]
    assert f.current_hp<1000
    offered=[p for p in prompts if p.get('affected')=='Visitor'
             and any(o.get('label')=='Knocked Prone' for o in (p.get('choice') or {}).get('options',[]))]
    assert bool(offered)==(not grown), 'the Prone/push menu is offered only for a target Large or smaller right now'
    assert any(x.condition_id.endswith('.prone') for x in f.conditions.values())==(not grown)


def test_absolute_size_cap_reads_a_wide_sealed_footprint_not_the_defaulted_label():
    """An old sealed fight can carry a three-cell-wide footprint while its template label defaulted to Medium.
    dynamic_size.base_category reads that width, so the cap sees the creature's real size (Huge): Horse-Cutting
    Arc still deals its damage but offers no Large-or-smaller Prone/push rider."""
    from combat.footprints import ActorFootprintDefinition
    from tests.test_riders_c5 import _answers, _crowd, _use, SAB

    engine,me,foes=_crowd([SAB+'horse_cutting_arc'],foes=1,dc=50)
    foe=foes[0]
    foe.size_category='Medium'
    engine.actor_footprints[foe.entity_id]=ActorFootprintDefinition.rectangle(3,3,
        footprint_id='footprint:legacy.3x3',source_definition_id='test:legacy-wide-footprint')
    assert engine._footprint(foe).width_cells==3
    requests=_answers(engine,{})
    arc=next(c for c in engine.legal_candidates() if c.actor_id==me.entity_id and c.display_name.startswith('Horse-Cutting Arc'))
    from combat.gate2_runtime_models import ActionIntent
    engine.execute_intent(ActionIntent(intent_id='legacy-arc',decision_id=arc.decision_id,candidate_id=arc.candidate_id,
        state_version=arc.state_version,actor_id=me.entity_id,target_ids=arc.target_ids,destination=arc.destination))
    assert not [r for r in requests if str(r['reaction_source_id']).endswith('battleline_outcome')], \
        'a three-cell-wide creature is Huge, so the Large-or-smaller rider is not offered'
    assert not any(c.condition_id=='condition:typed.prone' for c in foe.conditions.values())


def _scare_table(tmp_path, scared=True):
    """Three sealed fighters: the Keeper (Sabers, Dao) against two Visitors, both on the other team. A bundle_edit
    drops the struck Visitor to 1 HP so Forward Cut's kill fires Saber Scare's printed drop-to-0 branch."""
    import copy, json, zipfile
    from combat.canonical import canonical_sha256
    from combat.factory_compiler import compile_character
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    from tests.h1_support import ROOT, sheet
    from tests.test_carry import KIT
    from tests.hunt15_support import LEFT as L, RIGHT as R

    bundles=[]
    for aid,owned,kit,label,hp in ((L,[P+'saber_scare',P+'forward_cut'],DAO,'Keeper',1000),
                                   (R,[],KIT,'Visitor',1),
                                   (OTHER,[],KIT,'Second visitor',1000)):
        doc=sheet(list(owned),cl=15,dc=100,kit={'starting_kit':kit})
        doc['identity']['display_name']=label
        doc.setdefault('spheres_and_talents',{})['sphere_record_ids']=[]
        doc['spheres_and_talents']['automatic_sphere_component_record_ids']=[]
        stats=doc['ability_scores_and_statistics']
        stats['technique_attack_bonus']=100
        stats['primary_resource']['maximum']=100
        stats['hit_points']['maximum']=hp
        folder=tmp_path/'portable_characters'/aid.removeprefix('actor:factory.')
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder/'current.zip','w') as z:z.writestr('Tianxia_Owner_Character_Sheet_v1.json',json.dumps(doc))
        owned_talents=list(owned) if scared else [P+'forward_cut']
        doc2=sheet(owned_talents,cl=15,dc=100,kit={'starting_kit':kit})
        doc2['identity']['display_name']=label
        doc2.setdefault('spheres_and_talents',{})['sphere_record_ids']=[]
        doc2['spheres_and_talents']['automatic_sphere_component_record_ids']=[]
        s2=doc2['ability_scores_and_statistics']
        s2['technique_attack_bonus']=100
        s2['primary_resource']['maximum']=100
        s2['hit_points']['maximum']=hp
        with zipfile.ZipFile(folder/'current.zip','w') as z:z.writestr('Tianxia_Owner_Character_Sheet_v1.json',json.dumps(doc2))
        bundles.append(compile_character(doc2,actor_id=aid,reaction_plan={'ask':True}))
    combat=CombatService(ROOT,tmp_path)
    mid=combat._finish_factory_match(bundles,[L,R,OTHER],{L:'team:a',R:'team:b',OTHER:'team:b'},
        {L:{'x':3,'y':6},R:{'x':4,'y':6},OTHER:{'x':4,'y':5}},
        combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena'],[L],[R,OTHER],
        control_modes={L:'MANUAL',R:'MANUAL',OTHER:'MANUAL'},match_seed='scare',
        display_name='Saber Scare regression',maximum_rounds=10)['match_id']
    table=TabletopService(combat,tmp_path)
    turn(table,mid,L)
    return combat,table,mid


def _walk_away(c,t,m,who,from_who):
    """One ordinary movement step by ``who`` out of ``from_who``'s reach, through the table's own candidate."""
    engine=c._load_session(m).engine
    foe=engine.state.actors[from_who]
    move=next(k for k in engine.legal_candidates() if k.actor_id==who and k.destination is not None
              and engine._distance_actor_to_actor(engine.state.actors[who],foe,actor_position=k.destination)>5)
    st=t.state(m)
    return st,move


def test_saber_scare_asks_at_the_table_and_the_frightened_creature_loses_its_opportunity_attack(tmp_path):
    """Player-owned Ask me transport: the choice arrives as a table REACTION_REQUIRED naming the ability, the
    action that triggered it and the creatures involved, the answer commits, and the reaction_denied condition is
    still there after a reload. It also really denies an Opportunity Attack: once the Keeper walks away from the
    frightened Visitor, that creature makes no attack, while the control fight's unfrightened Visitor does."""
    from tests.test_auto42_stars import resolve

    c,t,m=_scare_table(tmp_path)
    def pick(p):
        src=p['context']['reaction_source_id']
        if src=='choice:needle.saber_scare':
            return [o['id'] for o in p['choice']['options'] if o.get('label')=='Second visitor']
        return [o['id'] for o in (p.get('choice') or {}).get('options',[])] [:1]
    _,prompts=settle(action_sender(c,t,m,'Forward Cut',target_id=RIGHT),pick)
    scares=[p for p in prompts if p['context']['reaction_source_id']=='choice:needle.saber_scare']
    assert scares, 'the printed choice of one hostile creature must be asked of the player at the table'
    asked=scares[0]
    assert asked['reaction']=='Saber Scare' and asked['action']=='Forward Cut', \
        'the question names the ability and the action that triggered it'
    assert 'Visitor' in asked['moment'], 'the question names the creature that was dropped'
    e=reload(c,m)
    assert not e.state.actors[RIGHT].active, 'the struck creature was dropped to 0 HP'
    visitor=e.state.actors[OTHER]
    assert any(x.condition_id=='condition:typed.reaction_denied' for x in visitor.conditions.values()), \
        'the frightened condition is a saved one'
    st,move=_walk_away(c,t,m,LEFT,OTHER)  # the Keeper walks out of the Visitor's reach
    resolve(lambda answers:t.act(m,move.candidate_id,st['menu']['decision_id'],st['menu']['state_version'],st['last_sequence'],answers))
    e=reload(c,m)
    assert not [x for x in e.events if x.event_type=='ATTACK_ROLLED' and x.actor_id==OTHER], \
        'a creature that cannot take Reactions makes no Opportunity Attack'


def _walk_into(c,t,m,who,toward_who):
    """One ordinary movement step by ``who`` that ends inside ``toward_who``'s reach, so that the next
    ordinary step away from it provokes that creature's Opportunity Attack."""
    from tests.test_auto42_stars import resolve
    engine=c._load_session(m).engine
    foe=engine.state.actors[toward_who]
    move=next(k for k in engine.legal_candidates() if k.actor_id==who and k.destination is not None
              and engine._distance_actor_to_actor(engine.state.actors[who],foe,actor_position=k.destination)<=5
              and k.destination!=engine.state.actors[who].position)
    st=t.state(m)
    resolve(lambda answers:t.act(m,move.candidate_id,st['menu']['decision_id'],st['menu']['state_version'],st['last_sequence'],answers))


def test_saber_scare_leaves_the_control_fighter_able_to_make_its_opportunity_attack(tmp_path):
    """The same table without Saber Scare: the control Visitor answers the Keeper's retreat with a real
    Opportunity Attack, so the denial in the test above is the ability's doing."""
    from tests.test_auto42_stars import resolve

    c,t,m=_scare_table(tmp_path,scared=False)
    settle(action_sender(c,t,m,'Forward Cut',target_id=RIGHT),lambda p:[o['id'] for o in (p.get('choice') or {}).get('options',[])][:1])
    st,move=_walk_away(c,t,m,LEFT,OTHER)
    _,prompts=resolve(lambda answers:t.act(m,move.candidate_id,st['menu']['decision_id'],st['menu']['state_version'],st['last_sequence'],answers))
    e=reload(c,m)
    assert [x for x in prompts if x.get('reaction','').startswith('Opportunity')], \
        'the control Visitor is asked for its Opportunity Attack'
    assert [x for x in e.events if x.event_type=='ATTACK_ROLLED' and x.actor_id==OTHER], \
        'an unfrightened creature still makes its Opportunity Attack'


def _seal_guard_pressure(bundle):
    """Give the Keeper a synthetic, sealed ability that Guard Pressures a chosen creature, so Forward Cut's
    "if the target is Guard Pressured" branch is reached through typed authority and a real table action
    (commit + reload) rather than by writing a mark onto a live engine."""
    if bundle['actor_template']['entity_id']!=LEFT:
        return
    sid='action:test.guard_pressure'
    bundle['actor_template']['action_ids'].append(sid)
    bundle['action_catalog'].append({'source_definition_id':sid,'display_name':'Guard Pressure','owner_id':LEFT,
        'economy':'NONE','resolution_kind':'TYPED','target_kind':'HOSTILE_ENTITY','range_ft':60,'costs':[],
        'parameters':{'typed':{'effects':[{'type':'mark','mark':'Guard Pressured','applies_to':'target',
            'duration':{'kind':'until_start_of_your_next_turn'}}],'numbers':{},'duration':{'kind':'instant'},'riders':[]}}})


def _step_table(tmp_path):
    """Three sealed fighters on the real table: the Keeper (Sabers, Dao, Forward Cut) against two Visitors on
    the other team, both at full health so each can still act after the hit. As in the Saber Scare table, the
    Keeper also owns a sealed Guard Pressure action, used here to reach Forward Cut's marked branch honestly."""
    import json, zipfile
    from combat.factory_compiler import compile_character
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    from tests.h1_support import ROOT, sheet
    from tests.test_carry import KIT

    bundles=[]
    for aid,owned,kit,label in ((LEFT,[P+'forward_cut'],DAO,'Keeper'),
                                (RIGHT,[],KIT,'Visitor'),
                                (OTHER,[],KIT,'Second visitor')):
        doc=sheet(list(owned),cl=15,dc=100,kit={'starting_kit':kit})
        doc['identity']['display_name']=label
        doc.setdefault('spheres_and_talents',{})['sphere_record_ids']=[]
        doc['spheres_and_talents']['automatic_sphere_component_record_ids']=[]
        stats=doc['ability_scores_and_statistics']
        stats['technique_attack_bonus']=100
        stats['primary_resource']['maximum']=100
        stats['hit_points']['maximum']=1000
        folder=tmp_path/'portable_characters'/aid.removeprefix('actor:factory.')
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder/'current.zip','w') as z:z.writestr('Tianxia_Owner_Character_Sheet_v1.json',json.dumps(doc))
        bundle=compile_character(doc,actor_id=aid,reaction_plan={'ask':True})
        _seal_guard_pressure(bundle)
        from combat.canonical import canonical_sha256
        bundle.pop('bundle_sha256',None);bundle['bundle_sha256']=canonical_sha256(bundle)
        bundles.append(bundle)
    combat=CombatService(ROOT,tmp_path)
    mid=combat._finish_factory_match(bundles,[LEFT,RIGHT,OTHER],{LEFT:'team:a',RIGHT:'team:b',OTHER:'team:b'},
        {LEFT:{'x':3,'y':6},RIGHT:{'x':4,'y':6},OTHER:{'x':4,'y':5}},
        combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena'],[LEFT],[RIGHT,OTHER],
        control_modes={a:'MANUAL' for a in (LEFT,RIGHT,OTHER)},match_seed='forward-cut-step',
        display_name='Forward Cut step regression',maximum_rounds=10)['match_id']
    table=TabletopService(combat,tmp_path)
    turn(table,mid,LEFT)
    return combat,table,mid


def _answer(send, picker):
    """Answer every asked reaction through the table. A reaction with no choice menu (an Opportunity Attack
    offers its strike directly) is answered USE, the way tests/test_auto42_stars.resolve does; ``picker``
    chooses among a reaction's offered option ids."""
    answers, prompts = [], []
    for _ in range(12):
        result = send(answers)
        if result['status'] != 'REACTION_REQUIRED':
            assert result['status'] == 'COMMITTED', result
            return result, prompts
        p = result['reaction']
        prompts.append(p)
        ids = [o['id'] for o in (p.get('choice') or {}).get('options', [])]
        chosen = picker(p) if picker else ids[:1]
        answers.append({**p['context'], 'selection': 'USE' if chosen or not p.get('choice') else 'DECLINE',
                        'option_ids': chosen})
    raise AssertionError('too many choices')


def test_forward_cut_step_is_asked_moves_and_frees_only_the_hit_target(tmp_path):
    """Printed: "If the target is Guard Pressured, you may also move 5 feet after the hit without provoking
    Opportunity Attacks from that target."

    This is a table test, so the player-owned decision really goes through answer -> commit -> reload. The
    Keeper Guard Pressures the Visitor, hits it, and accepts a legal five-foot step that leaves BOTH visitors
    out of reach: the Second visitor, which the printed text does not excuse, really makes its Opportunity
    Attack, while the Visitor the step was aimed at makes none. Later ordinary movement out of that Visitor's
    reach provokes it again, so the exemption is the step itself and not a turn-long or blanket waiver."""
    from tests.test_auto42_stars import resolve

    c,t,m=_step_table(tmp_path)
    settle(action_sender(c,t,m,'Guard Pressure',target_id=RIGHT))
    assert any(x.condition_id==mark_condition_id('Guard Pressured',LEFT) for x in reload(c,m).state.actors[RIGHT].conditions.values()), \
        'the Visitor is Guard Pressured by a committed, reloaded action'
    engine=c._load_session(m).engine
    walker=engine.state.actors[LEFT]
    turns_started=walker.turns_started
    def cell_of(option):
        x,y=str(option).split(':',1)[1].split(',')[:2]
        return Position(x=int(x),y=int(y),z=0)
    def pick(p):
        if p['context']['reaction_source_id']!='choice:needle.rider_step':
            return [o['id'] for o in (p.get('choice') or {}).get('options', [])][:1]
        ids=[o['id'] for o in p['choice']['options']]
        cells=[o for o in ids if str(o).startswith('cell:') and cell_of(o)!=walker.position
               and all(engine._distance_actor_to_actor(walker,engine.state.actors[aid],actor_position=cell_of(o))>5
                       for aid in (RIGHT,OTHER))]
        assert cells, "the printed five feet must offer a real cell outside both creatures' reach"
        return [cells[0]]
    _,prompts=_answer(action_sender(c,t,m,'Forward Cut',target_id=RIGHT),pick)
    assert [p for p in prompts if p['context']['reaction_source_id']=='choice:needle.rider_step'], \
        'the printed five feet is a player decision, so it must be asked at the table'
    e=reload(c,m)
    assert [x for x in e.events if x.event_type=='ATTACK_ROLLED' and x.actor_id==OTHER], \
        'another eligible creature the step left in reach still makes its Opportunity Attack'
    assert not [x for x in e.events if x.event_type=='ATTACK_ROLLED' and x.actor_id==RIGHT], \
        'the hit target, the one creature the printed text excuses, makes none'
    assert all(e._distance_actor_to_actor(e.state.actors[LEFT],e.state.actors[aid])>5 for aid in (RIGHT,OTHER)), \
        'the accepted five-foot step really moved the Keeper outside both creatures\' reach'
    assert e.state.actors[RIGHT].reaction_available, 'the protected step did not spend the hit target\'s reaction'
    # The exemption is the step, not the turn: walk back into the Visitor's reach, and ordinary movement out
    # of it again then provokes that same creature.
    _walk_into(c,t,m,LEFT,RIGHT)
    e=reload(c,m)
    assert e.state.current_actor_id==LEFT and e.state.actors[LEFT].turns_started==turns_started, \
        'the return to reach happens on the same Keeper turn as the protected step'
    assert e._distance_actor_to_actor(e.state.actors[LEFT],e.state.actors[RIGHT])<=5
    assert e.state.actors[RIGHT].reaction_available
    st,move=_walk_away(c,t,m,LEFT,RIGHT)
    _,later=resolve(lambda answers:t.act(m,move.candidate_id,st['menu']['decision_id'],st['menu']['state_version'],st['last_sequence'],answers))
    assert [x for x in later if x.get('reaction','').startswith('Opportunity')], \
        "ordinary movement on the same turn still asks the Visitor for an Opportunity Attack"
    e=reload(c,m)
    assert e.state.current_actor_id==LEFT and e.state.actors[LEFT].turns_started==turns_started
    assert [x for x in e.events if x.event_type=='ATTACK_ROLLED' and x.actor_id==RIGHT], \
        'the exempted target attacks on the same turn\'s ordinary retreat, through commit and reload'
    assert not e.state.actors[RIGHT].reaction_available
