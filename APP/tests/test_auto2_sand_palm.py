"""Glass-Cutting Palm from finalized Insight identity, through table and cold replay."""
import pytest
from tests import worker2_support as W
from tests.cw2_service_support import add_action, seal
from tests.test_auto50_sand import prepare_sand

PALM='insight.glass-cutting-palm'
EDGE='TAL_SAND_GLASS_EDGE_SCRIPTURE'


def fight(tmp_path,monkeypatch,*,cl=15,owned=True,native=False,kind='weapon',buried=False,terrain=True,other=False,ranged=False,glass=False,push_on_hit=False):
    original=W.sheet
    def sheet(mids,**kwargs):
        doc=original(mids,**kwargs)
        if owned and EDGE in mids:
            doc.setdefault('spheres_and_talents',{})['cultivation_insight_record_ids']=[PALM]
        return doc
    monkeypatch.setattr(W,'sheet',sheet)
    def prepare(bundles):
        prepare_sand(bundles)
        if glass:
            for bundle in bundles:
                typed=next(a for a in bundle['action_catalog'] if a['display_name']=='Prepare Sand Terrain')['parameters']['typed']
                if glass=='other_sphere':typed['sphere']='tianxia.sphere.earth'
                typed['effects'][0]['terrain']=['glass terrain']
                typed['zone_spec']['terrain']=['glass terrain']
                typed['zone_spec']['visual']['material']='glass'
                seal(bundle)
        add_action(bundles[0],'Prepare Burial',[{'type':'sand_bury','applies_to':'target','duration':'one_minute'}])
        if native:
            source=W.sealed_native_attack(bundles[0],'Palm Strike',range_ft=60 if ranged else None,attack_bonus=100,count=1,sides=2,modifier=0)
            row=next(a for a in bundles[0]['action_catalog'] if a['source_definition_id']==source)
            row['parameters']['attack_kind']=kind
            row['economy']='NONE'
            seal(bundles[0])
        else:
            add_action(bundles[0],'Palm Strike',[{'type':'attack','attack_kind':kind,
                'on_hit':[{'type':'damage','flat':1,'damage_types':['bludgeoning']}]}],
                typed={'weapon':{'ability_modifier':2},'range_ft':60 if ranged else None,
                       'numbers':{'pb':4,'key_mod':2,'cl':cl,'attack_bonus':100}})
    if push_on_hit:
        original_prepare=prepare
        def prepare(bundles):
            original_prepare(bundles)
            for bundle in bundles:
                terrain=next(a for a in bundle['action_catalog'] if a['display_name']=='Prepare Sand Terrain')['parameters']['typed']
                terrain['area']['size_ft']=5
                terrain['zone_spec']['size_ft']=5
                seal(bundle)
            typed=next(a for a in bundles[0]['action_catalog'] if a['display_name']=='Palm Strike')['parameters']['typed']
            typed['effects'][0]['on_hit'].append({'type':'forced_movement','applies_to':'target','distance_ft':30,'direction':'away'})
            seal(bundles[0])
    c,t,m=W.fixture(tmp_path,[EDGE],cl=cl,bundle_transform=prepare,
                    positions={W.OWNER:{'x':3,'y':6},W.ALLY:{'x':3,'y':7},W.FOE:{'x':4,'y':6}})
    if terrain:
        who=W.ALLY if other else W.OWNER
        W.turn(t,m,who);W.settle(t,m,W.candidate(c,m,'Prepare Sand Terrain').candidate_id);W.turn(t,m,W.OWNER)
    if buried: W.settle(t,m,W.candidate(c,m,'Prepare Burial',target=W.FOE).candidate_id)
    return c,t,m


def bonus(engine):
    return [e for e in engine.events if e.event_type=='DAMAGE_COMMITTED' and e.payload.get('display_source_id', e.source_definition_id)==PALM]


@pytest.mark.parametrize('native,kind',[(False,'weapon'),(False,'unarmed'),(True,'weapon'),(True,'unarmed'),(True,'weapon_melee')])
@pytest.mark.parametrize('cl,buried,amount',[(8,False,4),(14,True,4),(15,True,6)])
def test_palm_optional_printed_amount_once_turn_reload_and_refresh(tmp_path,monkeypatch,native,kind,cl,buried,amount):
    c,t,m=fight(tmp_path,monkeypatch,native=native,kind=kind,cl=cl,buried=buried)
    cp=W.reload(tmp_path,m).state.actors[W.OWNER].resources.copy()
    cid=W.candidate(c,m,'Palm Strike',target=W.FOE).candidate_id
    prompts=W.settle(t,m,cid,{'choice:needle.sand_glass_palm':'use'})
    e=W.reload(tmp_path,m);hits=bonus(e)
    assert len(hits)==1 and hits[0].payload['reduced_to']==amount and hits[0].payload['damage_type']=='PIERCING'
    assert any(p['context']['reaction_source_id']=='choice:needle.sand_glass_palm' for p in prompts)
    assert e.state.actors[W.OWNER].resources==cp
    W.settle(t,m,W.candidate(c,m,'Palm Strike',target=W.FOE).candidate_id,{'choice:needle.sand_glass_palm':'use'})
    assert len(bonus(W.reload(tmp_path,m)))==1
    W.settle(t,m,t.state(m)['menu']['end_turn']);W.turn(t,m,W.OWNER)
    W.settle(t,m,W.candidate(c,m,'Palm Strike',target=W.FOE).candidate_id,{'choice:needle.sand_glass_palm':'use'})
    assert len(bonus(W.reload(tmp_path,m)))==2


def test_decline_palm_does_not_consume_turn_allowance(tmp_path,monkeypatch):
    c,t,m=fight(tmp_path,monkeypatch)
    W.settle(t,m,W.candidate(c,m,'Palm Strike',target=W.FOE).candidate_id,{'choice:needle.sand_glass_palm':None})
    assert not bonus(W.reload(tmp_path,m))
    W.settle(t,m,W.candidate(c,m,'Palm Strike',target=W.FOE).candidate_id,{'choice:needle.sand_glass_palm':'use'})
    assert len(bonus(W.reload(tmp_path,m)))==1


@pytest.mark.parametrize('opts',[{'owned':False},{'cl':7},{'terrain':False},{'other':True},{'kind':'cultivation'}])
def test_palm_requires_owned_insight_gate_owned_terrain_and_melee_delivery(tmp_path,monkeypatch,opts):
    c,t,m=fight(tmp_path,monkeypatch,**opts)
    prompts=W.settle(t,m,W.candidate(c,m,'Palm Strike',target=W.FOE).candidate_id,{'choice:needle.sand_glass_palm':'use'})
    assert not bonus(W.reload(tmp_path,m))
    assert not any(p['context']['reaction_source_id']=='choice:needle.sand_glass_palm' for p in prompts)


@pytest.mark.parametrize('native',[False,True])
def test_palm_adjacent_ranged_hit_is_not_melee(tmp_path,monkeypatch,native):
    c,t,m=fight(tmp_path,monkeypatch,native=native,ranged=True)
    prompts=W.settle(t,m,W.candidate(c,m,'Palm Strike',target=W.FOE).candidate_id,{'choice:needle.sand_glass_palm':'use'})
    assert not bonus(W.reload(tmp_path,m))
    assert not any(p['context']['reaction_source_id']=='choice:needle.sand_glass_palm' for p in prompts)


@pytest.mark.parametrize('native',[False,True])
def test_palm_accepts_owned_glass_terrain(tmp_path,monkeypatch,native):
    c,t,m=fight(tmp_path,monkeypatch,native=native,glass=True)
    W.settle(t,m,W.candidate(c,m,'Palm Strike',target=W.FOE).candidate_id,{'choice:needle.sand_glass_palm':'use'})
    assert len(bonus(W.reload(tmp_path,m)))==1


@pytest.mark.parametrize('native,other',[(False,False),(True,False),(False,True)])
def test_palm_other_sphere_glass_requires_owner_creator(tmp_path,monkeypatch,native,other):
    c,t,m=fight(tmp_path,monkeypatch,native=native,glass='other_sphere',other=other)
    W.settle(t,m,W.candidate(c,m,'Palm Strike',target=W.FOE).candidate_id,{'choice:needle.sand_glass_palm':'use'})
    assert bool(bonus(W.reload(tmp_path,m)))== (not other)


@pytest.mark.parametrize('native',[False,True])
def test_palm_follows_actual_redirected_hit_not_declared_target(tmp_path,monkeypatch,native):
    from combat import ext
    ext.effects()
    c,t,m=fight(tmp_path,monkeypatch,native=native,buried=True)
    state=c._load_session(m).engine.state
    c.change_relations(m,change={'kind':'ACTOR_RELATION','subject':W.OWNER,'other':W.ALLY,'relation':'ENEMY'},
                       expected_state_version=state.state_version)
    monkeypatch.setitem(ext._HOOKS,'retarget_attack',[
        lambda engine,attacker,defender,intent,context: {'source_id':'test:interpose','target_id':W.ALLY}
        if attacker.entity_id==W.OWNER and defender.entity_id==W.FOE else None])
    W.settle(t,m,W.candidate(c,m,'Palm Strike',target=W.FOE).candidate_id,{'choice:needle.sand_glass_palm':'use'})
    e=W.reload(tmp_path,m)
    assert any(event.event_type=='ATTACK_RETARGETED' for event in e.events)
    hits=bonus(e)
    assert len(hits)==1 and hits[0].target_ids==(W.ALLY,)
    assert hits[0].payload['reduced_to']==4  # the declared target is Buried; the creature actually struck is not
    assert e.state.actors[W.FOE].current_hp==60


def test_palm_uses_contact_at_hit_before_on_hit_movement(tmp_path,monkeypatch):
    from combat.ext.sand_terrain import standing_in
    c,t,m=fight(tmp_path,monkeypatch,push_on_hit=True)
    before=W.reload(tmp_path,m)
    assert standing_in(before,W.OWNER,before.state.actors[W.FOE])
    W.settle(t,m,W.candidate(c,m,'Palm Strike',target=W.FOE).candidate_id,{'choice:needle.sand_glass_palm':'use'})
    e=W.reload(tmp_path,m)
    assert not standing_in(e,W.OWNER,e.state.actors[W.FOE]), e.state.actors[W.FOE].position
    assert len(bonus(e))==1
