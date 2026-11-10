"""Second-pass Lightning mechanics through committed tables and cold replay."""
import pytest
from combat.typed_executor import mark_condition_id
from tests.auto_worker1_support import fight, LEFT, RIGHT, ALLY, act, reload, turn, action_sender
from combat.ext import lightning_riders as L

VOLLEY = 'TAL_LIGHTNING_THOUSAND_SPARK_VOLLEY'
LASH = 'TAL_LIGHTNING_LIGHTNING_LASH'
GROUND = 'TAL_LIGHTNING_GROUNDING_BREATH'
SECOND = 'actor:factory.auto111-witness'
QI = 'resource:core.qi'


def answer(send, *, accept=True, pick=None):
    result = send([])
    answers, prompts = [], []
    while result['status'] == 'REACTION_REQUIRED':
        p = result['reaction']; prompts.append(p)
        options = [o['id'] for o in (p.get('choice') or {}).get('options', [])]
        choice = pick(p, options) if pick else options[:1] if accept else []
        answers.append({**p['context'], 'selection': 'USE' if choice else 'DECLINE', 'option_ids': choice})
        result = send(answers)
    assert result['status'] == 'COMMITTED', result
    return prompts


@pytest.mark.parametrize('hit,ai', [(True, False), (False, False), (True, True), (False, True)])
def test_cultivation_volley_hit_miss_and_enemy_secondary(tmp_path, hit, ai):
    combat, table, mid = fight(tmp_path, [VOLLEY], left_attack_bonus=100 if hit else -100,
        ally=(), extra_witness=True, positions={LEFT:{'x':3,'y':6}, RIGHT:{'x':6,'y':6},
            ALLY:{'x':6,'y':5}, SECOND:{'x':7,'y':6}})
    turn(table, mid, LEFT)
    send = action_sender(combat, table, mid, 'Thousand-Spark Volley: Cultivation Attack', ai=ai, target_id=RIGHT)
    prompts = answer(send, pick=lambda p, opts: [SECOND] if SECOND in opts else [])
    engine = reload(combat, mid)
    owner, primary, secondary, ally = [engine.state.actors[a] for a in (LEFT, RIGHT, SECOND, ALLY)]
    assert owner.resources[QI] == 98
    assert primary.current_hp < 1000 if hit else primary.current_hp == 1000
    assert secondary.current_hp < 1000
    assert ally.current_hp == 1000 and not ally.conditions
    assert bool(any(c.condition_id == mark_condition_id('Charged', LEFT) for c in primary.conditions.values())) == hit
    if hit:
        assert any(c.condition_id.endswith('reaction_denied') for c in secondary.conditions.values())
    else:
        assert secondary.current_hp == 996
    assert not any(e.event_type == 'GM_RIDER' and 'Cultivation Attack alternative' in str(e.payload) for e in engine.events)
    for p in prompts:
        assert ALLY not in [o['id'] for o in (p.get('choice') or {}).get('options', [])]


@pytest.mark.parametrize('accept,proficient', [(True, False), (False, False), (True, True)])
def test_grounding_choice_and_recorded_proficiency(tmp_path, accept, proficient):
    def edit(doc, aid):
        if aid == LEFT and proficient:
            stats = doc['ability_scores_and_statistics']
            mods = {r['ability']:r['modifier'] for r in stats['abilities']}
            stats['saving_throws'] = {'DEX': int(mods['DEX']) + 4}
            stats['saving_throw_proficiencies'] = ['DEX']
    combat, table, mid = fight(tmp_path, [GROUND], sheet_edit=edit,
        cause=[{'type':'save','ability':'dex','on_fail':[{'type':'damage','flat':1,'damage_types':['lightning']}]}])
    turn(table, mid, RIGHT)
    prompts = answer(action_sender(combat, table, mid, 'Cause', target_id=LEFT), accept=accept)
    engine = reload(combat, mid)
    grounding = [p for p in prompts if 'Grounding Breath' in str(p)]
    assert bool(grounding) == (not proficient)
    assert bool(engine.state.actors[LEFT].turn_flags.get('grounding_breath_used')) == (accept and not proficient)
    saves = [e for e in engine.events if e.event_type == 'SAVE_ROLLED' and e.actor_id == LEFT]
    assert saves
    assert saves[-1].payload["modifier"] == (6 if proficient else 2)
    assert saves[-1].payload["dc"] == (96 if accept and not proficient else 100)
    before = len(grounding)
    # Declining preserves the benefit; using it prevents another offer before next turn.
    again = answer(action_sender(combat, table, mid, 'Cause', target_id=LEFT), accept=False)
    assert bool([p for p in again if 'Grounding Breath' in str(p)]) == (not accept and not proficient)
    reload(combat, mid)


@pytest.mark.parametrize('accept,dc', [(True,100),(True,1),(False,100)])
def test_meridian_on_actual_melee_conductive_strike(tmp_path, accept,dc):
    combat, table, mid = fight(tmp_path, ['TAL_LIGHTNING_CONDUCTIVE_STRIKE', L.MERIDIAN],
        left_score=30,left_save_dc=dc)
    turn(table, mid, LEFT)
    prompts = answer(action_sender(combat, table, mid, 'Bi Shou (Dagger) attack', target_id=RIGHT),
                     pick=lambda p, opts: ['INTENSIFY'] if accept and 'INTENSIFY' in opts else [])
    assert any('Meridian-Stopping Spark' in str(p) for p in prompts)
    engine = reload(combat, mid)
    assert engine.state.actors[LEFT].resources[QI] == (99 if accept else 100)
    target = engine.state.actors[RIGHT]
    assert bool(any(c.condition_id.endswith('no_cp_regain') for c in target.conditions.values())) == accept
    assert bool(any(c.condition_id.endswith('reaction_denied') for c in target.conditions.values())) == (accept and dc==100)
    if accept:
        save=next(e for e in reversed(engine.events) if e.event_type=='SAVE_ROLLED')
        assert save.payload['dc']==dc


@pytest.mark.parametrize('accept', [True, False])
def test_meridian_on_selected_charged_needle(tmp_path, accept):
    dart = [{'item_id':'tianxia.mortal.weapon.fei_biao','name':'Fei Biao','quantity':1}]
    combat, table, mid = fight(tmp_path, ['TAL_LIGHTNING_CHARGED_NEEDLE', L.MERIDIAN],
        left_kit={"items":dart}, left_score=30,positions={LEFT:{"x":3,"y":6},RIGHT:{"x":6,"y":6}})
    turn(table, mid, LEFT)
    def choose(p, options):
        if 'INTENSIFY' in options: return ['INTENSIFY'] if accept else []
        return options[:1]
    prompts = answer(action_sender(combat, table, mid, 'Fei Biao (Flying Dart) thrown', target_id=RIGHT), pick=choose)
    assert any('Meridian-Stopping Spark' in str(p) for p in prompts)
    engine = reload(combat, mid)
    assert engine.state.actors[LEFT].resources[QI] == (99 if accept else 100)
    assert any(c.condition_id==mark_condition_id('Charged',LEFT) for c in engine.state.actors[RIGHT].conditions.values())
    assert bool(any(c.condition_id.endswith('no_cp_regain') for c in engine.state.actors[RIGHT].conditions.values())) == accept


@pytest.mark.parametrize('ai,accept', [(False,True),(False,False),(True,True)])
@pytest.mark.parametrize('unseen', [False, True])
def test_wings_burst_pass_damage_only_on_flight_and_once_per_turn(tmp_path, ai, accept, unseen):
    prepare = [{'type':'mark','mark':'Charged','applies_to':'target','duration':{'kind':'until_start_of_your_next_turn'}}]
    if unseen:
        prepare.append({'type':'condition', 'condition':'invisible', 'applies_to':'target', 'expires_on':'UNTIL_REMOVED'})
    combat, table, mid = fight(tmp_path, ['TAL_LIGHTNING_LIGHTNING_WINGS_BURST'], prepare=prepare,
        ally=(), prepare_target='ANY_CREATURE', positions={LEFT:{'x':3,'y':6}, RIGHT:{'x':5,'y':6}, ALLY:{'x':5,'y':5}})
    turn(table, mid, LEFT)
    assert act(table, mid, 'Prepare', target_id=RIGHT)['status']=='COMMITTED'
    assert act(table, mid, 'Prepare', target_id=ALLY)['status']=='COMMITTED'
    answer(action_sender(combat, table, mid, 'TAL_LIGHTNING_LIGHTNING_WINGS_BURST'), accept=False)
    def move(to, mode, automatic=False):
        state=table.state(mid);engine=combat._load_session(mid).engine
        c=next(c for c in engine.legal_candidates() if c.destination and
            (c.destination.x,c.destination.y,c.destination.z)==to and c.metadata.get('movement_mode','walk')==mode)
        if automatic:
            from combat.gate4_adapters import ManualControllerAdapter
            real=combat.controller
            class Fixed:
                def choose_primary_action(self, context):
                    return ManualControllerAdapter(lambda _:(c.candidate_id,())).choose_primary_action(context)
                def __getattr__(self, name): return getattr(real,name)
            combat.controller=Fixed();combat.set_controller_mode(mid,actor_id=LEFT,controller_mode='LOCAL_AUTO')
            send=lambda answers: table.auto_step(mid,table.state(mid)['last_sequence'],answers)
        else:
            send=lambda answers: table.act(mid,c.candidate_id,state['menu']['decision_id'],state['menu']['state_version'],state['last_sequence'],answers)
        return answer(send, pick=lambda p, opts:[RIGHT] if accept and RIGHT in opts else [])
    move((4,6,0),'walk')
    assert reload(combat,mid).state.actors[RIGHT].current_hp==1000
    from combat import stealth
    engine = reload(combat, mid)
    assert stealth.sees(engine, engine.state.actors[LEFT], engine.state.actors[RIGHT]) == (not unseen)
    prompts = move((4,6,1),'fly',ai)
    if not ai:
        wings = [p for p in prompts if p['context']['reaction_source_id'].endswith('wings_burst_pass')]
        assert wings and RIGHT in [o['id'] for o in wings[0]['choice']['options']]
    accept = accept and not (ai and unseen)
    assert reload(combat,mid).state.actors[RIGHT].current_hp==(996 if accept else 1000)
    assert reload(combat,mid).state.actors[ALLY].current_hp==1000
    if not ai:
        move((4,5,1),'fly')
        assert reload(combat,mid).state.actors[RIGHT].current_hp==(996 if accept else 1000)


@pytest.mark.parametrize('accept', [True,False])
def test_manual_electric_fist_adept_damage_and_scene_step(tmp_path, accept):
    def edit(doc, aid):
        if aid==LEFT:
            doc['spheres_and_talents']['cultivation_insight_record_ids']=['insight.electric-fist-adept']
    combat, table, mid=fight(tmp_path,[L.FIST],sheet_edit=edit,left_score=30)
    turn(table,mid,LEFT)
    before=reload(combat,mid).state.actors[LEFT].position
    def choose(p,opts):
        rid=p['context']['reaction_source_id']
        if rid.endswith('electric_fist'):return ['SHOCK']
        return opts[:1] if accept else []
    prompts=answer(action_sender(combat,table,mid,'Unarmed Strike',target_id=RIGHT),pick=choose)
    assert any('Electric Fist Adept' in str(p) for p in prompts)
    engine=reload(combat,mid);owner=engine.state.actors[LEFT]
    assert bool(owner.turn_flags.get('electric_fist_adept_round_scene_step'))==accept
    assert (owner.position != before)==accept
    packets=[e for e in engine.events if e.event_type=='DAMAGE_COMMITTED' and e.payload.get('display_source_id')=='insight.electric-fist-adept']
    assert len(packets)==(1 if accept else 0)
    if packets:assert packets[0].payload['reduced_to']==4
    assert owner.resources[QI]==100


@pytest.mark.parametrize('ai', [False, True])
@pytest.mark.parametrize('unseen', [False, True])
def test_ai_sky_fire_chooses_enemy_with_charged_ally_in_range(tmp_path, ai, unseen):
    prepare=[{'type':'mark','mark':'Charged','applies_to':'target','duration':{'kind':'until_start_of_your_next_turn'}}]
    combat,table,mid=fight(tmp_path,['TAL_LIGHTNING_CONDUCTIVE_STRIKE',L.MERIDIAN,L.NET],
        prepare=prepare,prepare_target='ANY_CREATURE',left_score=30,ally=(),extra_witness=True,
        extra_actions=[('Conceal', {'target_kind':'ANY_CREATURE', 'effects':[{'type':'condition', 'condition':'invisible', 'applies_to':'target', 'expires_on':'UNTIL_REMOVED'}]})],
        positions={LEFT:{'x':3,'y':6},RIGHT:{'x':4,'y':6},ALLY:{'x':4,'y':5},SECOND:{'x':5,'y':6}})
    turn(table,mid,LEFT)
    for target in [ALLY,SECOND]:assert act(table,mid,'Prepare',target_id=target)['status']=='COMMITTED'
    if unseen:
        # Conceal only the secondary recipient through a committed setup action.
        answer(action_sender(combat,table,mid,'Conceal',target_id=SECOND))
    from combat import stealth
    engine = reload(combat, mid)
    assert stealth.sees(engine, engine.state.actors[LEFT], engine.state.actors[SECOND]) == (not unseen)
    def choose(p, opts):
        return [SECOND] if SECOND in opts else opts[:1]
    prompts = answer(action_sender(combat,table,mid,'Bi Shou (Dagger) attack',target_id=RIGHT,ai=ai), pick=choose)
    if not ai:
        net = [p for p in prompts if p['context']['reaction_source_id'].endswith('sky_fire')]
        assert net and SECOND in [o['id'] for o in net[0]['choice']['options']]
    engine=reload(combat,mid)
    saves=[e.actor_id for e in engine.events if e.event_type=='SAVE_ROLLED']
    assert (SECOND in saves) == (not (ai and unseen))
    assert ALLY not in saves
    assert engine.state.actors[ALLY].current_hp==1000
    assert bool(any(c.condition_id.endswith('reaction_denied') for c in engine.state.actors[SECOND].conditions.values())) == (not (ai and unseen))
    assert not any(c.condition_id.endswith('reaction_denied') for c in engine.state.actors[ALLY].conditions.values())


@pytest.mark.parametrize('dc',[100,1])
def test_charged_needle_consumes_only_existing_charge_with_lightning_dc(tmp_path,dc):
    dart={'items':[{'item_id':'tianxia.mortal.weapon.fei_biao','quantity':1}]}
    combat,table,mid=fight(tmp_path,['TAL_LIGHTNING_CHARGED_NEEDLE'],left_kit=dart,left_score=30,
        left_save_dc=dc,positions={LEFT:{'x':3,'y':6},RIGHT:{'x':6,'y':6}},prepare=[{'type':'mark','mark':'Charged','applies_to':'target',
                                'duration':{'kind':'until_start_of_your_next_turn'}}])
    turn(table,mid,LEFT)
    assert act(table,mid,'Prepare',target_id=RIGHT)['status']=='COMMITTED'
    def choose(p,opts):return ['CONSUME'] if 'CONSUME' in opts else opts[:1]
    answer(action_sender(combat,table,mid,'Fei Biao (Flying Dart) thrown',target_id=RIGHT),pick=choose)
    engine=reload(combat,mid)
    target=engine.state.actors[RIGHT]
    assert not any(c.condition_id==mark_condition_id('Charged',LEFT) for c in target.conditions.values())
    assert any(c.condition_id.endswith('no_cp_regain') for c in target.conditions.values())
    save=next(e for e in reversed(engine.events) if e.event_type=='SAVE_ROLLED')
    assert save.payload['dc']==dc and save.payload['success']==(dc==1)
    assert engine.state.actors[LEFT].resources[QI]==100


def test_meridian_each_hit_in_one_needle_attack_sequence(tmp_path):
    """CL 15 Extra Attack: two hits and one miss; each hit may intensify once."""
    dart = {'items':[{'item_id':'tianxia.mortal.weapon.fei_biao','name':'Fei Biao','quantity':1}]}
    combat, table, mid = fight(tmp_path, ['TAL_LIGHTNING_CHARGED_NEEDLE', L.MERIDIAN,
        'tianxia.path.body_refining.feature.extra_attack'], left_kit=dart, left_score=30)
    turn(table, mid, LEFT)
    def choose(p, options):
        return ['INTENSIFY'] if 'INTENSIFY' in options else options[:1]
    prompts = answer(action_sender(combat, table, mid, 'Fei Biao (Flying Dart) attack', target_id=RIGHT), pick=choose)
    engine = reload(combat, mid)
    hits = [e for e in engine.events if e.event_type == 'ATTACK_ROLLED' and e.actor_id == LEFT]
    assert [e.payload['provisional_hit'] for e in hits] == [True, False, True]
    assert len([p for p in prompts if 'Meridian-Stopping Spark' in str(p)]) == 2
    assert engine.state.actors[LEFT].resources[QI] == 98


def test_meridian_same_hit_fist_and_conductive_intensifies_once(tmp_path):
    combat, table, mid = fight(tmp_path, [L.FIST, L.MERIDIAN, 'TAL_LIGHTNING_CONDUCTIVE_STRIKE'], left_score=30)
    turn(table, mid, LEFT)
    prompts = answer(action_sender(combat, table, mid, 'Bi Shou (Dagger) attack', target_id=RIGHT),
                     pick=lambda p, opts: ['INTENSIFY'] if 'INTENSIFY' in opts else [])
    engine = reload(combat, mid)
    assert engine.state.actors[LEFT].resources[QI] == 99
    assert len([p for p in prompts if 'INTENSIFY' in [o['id'] for o in (p.get('choice') or {}).get('options', [])]]) == 1


@pytest.mark.parametrize('proficient,other_bonus', [(False, 4), (True, -2)])
def test_grounding_preserves_bonus_and_penalty_with_explicit_provenance(tmp_path, proficient, other_bonus):
    def edit(doc, aid):
        if aid == LEFT:
            stats = doc['ability_scores_and_statistics']
            stats['saving_throw_proficiencies'] = ['DEX'] if proficient else []
            stats['saving_throws'] = {'DEX': 2 + (4 if proficient else 0) + other_bonus}
    combat, table, mid = fight(tmp_path, [GROUND], sheet_edit=edit,
        cause=[{'type':'save','ability':'dex','on_fail':[{'type':'damage','flat':1,'damage_types':['lightning']}]}])
    turn(table, mid, RIGHT)
    prompts = answer(action_sender(combat, table, mid, 'Cause', target_id=LEFT))
    engine = reload(combat, mid)
    assert bool([p for p in prompts if 'Grounding Breath' in str(p)]) == (not proficient)
    save = next(e for e in reversed(engine.events) if e.event_type == 'SAVE_ROLLED' and e.actor_id == LEFT)
    assert save.payload['modifier'] == 2 + (4 if proficient else 0) + other_bonus
    assert save.payload['dc'] == (100 if proficient else 96)
    assert bool(engine.state.actors[LEFT].turn_flags.get('grounding_breath_used')) == (not proficient)


def test_adept_scene_step_stays_spent_after_owner_turn_boundary(tmp_path):
    from combat.ext.needle import cell_id
    from combat.gate2_runtime_models import Position
    def edit(doc, aid):
        if aid == LEFT:
            doc['spheres_and_talents']['cultivation_insight_record_ids'] = ['insight.electric-fist-adept']
    combat, table, mid = fight(tmp_path, [L.FIST], sheet_edit=edit, left_score=30)
    turn(table, mid, LEFT)
    step = cell_id(Position(x=3, y=5))
    def choose(p, opts):
        return [step] if step in opts else opts[:1]
    first = answer(action_sender(combat, table, mid, 'Unarmed Strike', target_id=RIGHT), pick=choose)
    assert any(p['context']['reaction_source_id'].endswith('fist_adept_step') for p in first)
    assert reload(combat, mid).state.actors[LEFT].turn_flags['electric_fist_adept_round_scene_step']
    assert act(table, mid, 'end')['status'] == 'COMMITTED'
    turn(table, mid, LEFT)
    engine = reload(combat, mid)
    before = engine.state.actors[LEFT].position
    assert engine.state.actors[LEFT].turn_flags['electric_fist_adept_round_scene_step']
    second = answer(action_sender(combat, table, mid, 'Unarmed Strike', target_id=RIGHT))
    assert any(p['context']['reaction_source_id'].endswith('fist_adept_damage') for p in second)
    assert not any(p['context']['reaction_source_id'].endswith('fist_adept_step') for p in second)
    assert reload(combat, mid).state.actors[LEFT].position == before
