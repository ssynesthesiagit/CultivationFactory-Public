"""Review 1F20R regressions.

P1: journey rebuilds (acquisition, combat entry, restore into a new journey) must keep
owner equipment and saved reaction settings. P2: a calamity profile that expires
mid-round must not be offered to a later actor in that round.
"""
from combat.combat_world_facts import clock
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from factory_authoring.owner_items import OwnerItemStore, armour_choices, weapon_choices
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.worker2_support import candidate, turn

P = 'tianxia.subpath.qi.tribulation_vessel'
APID = '11111111-1111-4111-8111-111111111111'
BPID = '22222222-2222-4222-8222-222222222222'
A = 'actor:factory.' + APID
B = 'actor:factory.' + BPID
AXE = 'tianxia.mortal.weapon.fu'
LIGHT = 'tianxia.mortal.armor.lacquered_leather'

def game(tmp_path,monkeypatch,cl=18,acquire=True,profiles=(),width=12,owner_features=(),enemy_features=(),ask=False,source_dc=16,arena_document=None,enemy_attack=8,enemy_auto=False,enemy_ac=14,owner_proficient=(),qi_effective_cl=None,documents_out=None,ally_features=None,ally_project_id=None,saving_throws=None,profile_expires=100000,initiative=None):
    docs={x:sheet(['tianxia.path.qi_cultivation.feature.qi_sensing',*(owner_features if x=='vessel' else enemy_features)],cl=cl,dc=source_dc if x=='vessel' else 16,name=n,key='WIS',kit={'starting_kit':{'items':[{'item_id':'tianxia.mortal.weapon.bi_shou','name':'Bi Shou (Dagger)','quantity':1}]}}) for x,n in [('vessel','Wren'),('enemy','Mara')]}
    if ally_features is not None:
        docs['ally']=sheet(['tianxia.path.qi_cultivation.feature.qi_sensing',*ally_features],cl=cl,dc=16,name='Tobin',key='WIS')
    if saving_throws is not None:
        for key in ('enemy','ally'):
            if key in docs:docs[key]['ability_scores_and_statistics']['saving_throws']=dict(saving_throws)
    docs['enemy']['ability_scores_and_statistics']['technique_attack_bonus']=enemy_attack
    docs['enemy']['ability_scores_and_statistics']['armor_class']['base_value']=enemy_ac
    if enemy_auto:docs['vessel']['ability_scores_and_statistics']['initiative']={'bonus':30}
    for key,bonus in (initiative or {}).items():docs[key]['ability_scores_and_statistics']['initiative']={'bonus':bonus}
    if owner_proficient:
        docs['vessel']['ability_scores_and_statistics'].update(saving_throw_proficiencies=list(owner_proficient),saving_throws={a:6 for a in owner_proficient})
    for d in docs.values():d.setdefault('path_and_subpath',{}).update(path_record_id='tianxia.path.qi_cultivation',path_record_ids=['tianxia.path.qi_cultivation'],paths=[{'path_id':'tianxia.path.qi_cultivation','attainment':cl}])
    if qi_effective_cl is not None:docs['vessel']['path_and_subpath']['paths'][0]['effective_cl']=qi_effective_cl
    if documents_out is not None:documents_out.update(docs)
    ally_project_id=ally_project_id or '33333333-3333-4333-8333-333333333333'
    documents={APID:docs['vessel'],BPID:docs['enemy'],**({ally_project_id:docs['ally']} if ally_features is not None else {})}
    monkeypatch.setattr(CombatService,'_factory_owner_sheet',lambda self,pid:documents[pid])
    arena={'display_name':'Storm courtyard','stable_id':'battlefield:vessel-test','width_squares':width,'height_squares':width,'square_size_ft':5,'starting_positions':{},'terrain_regions':[]}
    if arena_document is not None:arena=arena_document
    monkeypatch.setattr(CombatService,'factory_arenas',lambda self,**kw:{'scene':arena})
    def cold():return CombatService(ROOT,tmp_path)
    if ask:
        TabletopService(cold(),tmp_path).save_reactions(APID,{'mode':'ask'})
    positions={A:{'x':3,'y':3},B:{'x':4,'y':3}}
    if ally_features is not None:positions['actor:factory.'+ally_project_id]={'x':3,'y':4}
    state=cold().create_journey(project_ids=list(documents),arena_id='scene',positions=positions,base_paces={aid:100 for aid in positions},control_modes={aid:'LOCAL_AUTO' if aid==B and enemy_auto else 'MANUAL' for aid in positions});jid=state['journey_id']
    def world(kind,scope,value,readers=None,expires_at=100000):
        before=cold().journey_state(jid)
        after=cold().journey_world_fact(jid,before['revision'],{'source':P,'subject':A,'kind':kind,'scope':scope,'value':value,'expires_at':expires_at,'readers':readers or [A]})
        assert cold().journey_state(jid)==after
        return after
    if callable(profiles):profiles=profiles(jid)
    if acquire:
        for index,profile in enumerate(profiles):world('calamity_profile','hazard-'+str(index),profile,expires_at=profile_expires)
        state=world('source_access','scripture',{'route':'restricted_scripture','source_rule':'The table owner grants access to a surviving Tribulation Vessel scripture.'})
        state=cold().journey_acquire_source(jid,state['revision'],A,P,{'access_scope':'scripture','hazard_scopes':['hazard-'+str(i) for i in range(len(profiles))]})
        assert not any(P in m for m in docs['vessel']['path_and_subpath']['path_feature_record_ids'])
    return cold,jid,world

def fight(cold,jid,tmp_path,maximum_rounds=20):
    state=cold().journey_state(jid);mid=cold().journey_start_combat(jid,state['revision'],{aid:'team:b' if aid==B else 'team:a' for aid in state['actors']},maximum_rounds=maximum_rounds)['match_id']
    service=cold();table=TabletopService(service,tmp_path)
    try:turn(table,mid,A)
    except Exception as exc:
        import traceback
        raise AssertionError('Native turn setup: '+traceback.format_exc().replace('\n',' | ')) from exc
    return service,table,mid

def loaded(cold,mid):
    s=cold()._load_session(mid);assert s.mechanical.replay()['status']=='PASS';return s.engine

def hazard(kind='Flame',cl=21):
    from combat.ext.mgr_reserve_tribulation_vessel_gather_calamity import DAMAGE
    return {'name':kind+' vent','source_rule':'An exposed natural vent imposes this genuine save and damage; it cannot refund its damage or normal Qi cost.','type':kind,'source_cl':cl,'damage_type':DAMAGE[kind][0],'dice':{'count':1,'sides':4},'dc':30,'save':'con','status':'growing','category':'environmental catastrophe','position':{'x':3,'y':3},'legendary':0,'formal_tribulation':0,'cost_qi':1,'genuine_threat':1}



FACE = 'Face Calamity: Flame vent'


def _give_owner_items(tmp_path):
    store = OwnerItemStore(tmp_path / 'owner_items')
    store.give(APID, {'kind': 'armour', 'chassis_id': LIGHT, 'grade': 'Spiritual',
                      'material_id': armour_choices(LIGHT, 'Spiritual', None, [])['material_id']})
    store.give(APID, {'kind': 'weapon', 'chassis_id': AXE, 'grade': 'Spiritual',
                      'material_id': weapon_choices(AXE, 'Spiritual', None, [])['material_id'],
                      'enchantment_ids': []})


def _names(catalog):
    if isinstance(catalog, dict):
        catalog = catalog['action_catalog']
    return {a['display_name'] if isinstance(a, dict) else a.display_name for a in catalog}


def _owner_equipment_premise(tmp_path, documents, full):
    """The owner equipment must change the compile, or the regression below proves nothing."""
    bare = compile_character(documents['vessel'], actor_id=A)
    assert full['armor_terms'] != bare['armor_terms']
    assert _names(full) - _names(bare)


def test_acquisition_combat_entry_and_cold_reload_keep_owner_equipment_and_settings(tmp_path, monkeypatch):
    _give_owner_items(tmp_path)
    documents = {}
    cold, jid, _ = game(tmp_path, monkeypatch, ask=True, documents_out=documents)
    full = CombatService(ROOT, tmp_path).compile_factory_actor(APID)
    _owner_equipment_premise(tmp_path, documents, full)
    # Acquisition rebuild (journey_acquire_source, gate5 ~line 505) keeps owner items and the saved reaction mode.
    bundle = cold().journey_state(jid)['actors'][A]['bundle']
    assert bundle['armor_terms'] == full['armor_terms']
    assert _names(full) <= _names(bundle)
    assert bundle['reaction_plan']['mode'] == 'ask'
    # Combat entry rebuild (journey_start_combat, gate5 ~line 611) and the cold reload keep them too.
    service, table, mid = fight(cold, jid, tmp_path)
    engine = loaded(cold, mid)
    assert _names(full) <= _names(engine.action_catalog.values())


def test_restore_into_new_journey_keeps_owner_equipment_and_settings(tmp_path, monkeypatch):
    _give_owner_items(tmp_path)
    documents = {}
    cold, jid, _ = game(tmp_path, monkeypatch, ask=True, documents_out=documents)
    full = CombatService(ROOT, tmp_path).compile_factory_actor(APID)
    _owner_equipment_premise(tmp_path, documents, full)
    state = cold().journey_state(jid)
    state = cold().journey_act(jid, state['revision'], A, 'finish', {})
    assert state['phase'] == 'finished'
    # Restoring the acquisition into a new journey rebuilds the bundle (journey.py create, ~line 534).
    state = cold().create_journey(project_ids=[APID], arena_id='scene', positions={A: {'x': 3, 'y': 3}},
                                  base_paces={A: 100}, control_modes={A: 'MANUAL'})
    bundle = state['actors'][A]['bundle']
    assert bundle['armor_terms'] == full['armor_terms']
    assert _names(full) <= _names(bundle)
    assert bundle['reaction_plan']['mode'] == 'ask'


def _offered(service, mid, name):
    try:
        candidate(service, mid, name)
        return True
    except AssertionError:
        return False


def test_calamity_expiring_mid_round_is_not_offered_to_later_actor(tmp_path, monkeypatch):
    # Enemy 40 > ally 20 > Vessel 0. Three slots of 2 s, so the Vessel acts at exactly 4 s:
    # after the profile expires at 3 s, but inside round one.
    cold, jid, _ = game(tmp_path, monkeypatch, cl=3, profiles=[hazard()], profile_expires=3,
                        ally_features=[], initiative={'enemy': 40, 'ally': 20, 'vessel': 0})
    service, table, mid = fight(cold, jid, tmp_path)
    assert clock(loaded(cold, mid)) == 4
    assert not _offered(service, mid, FACE)


def test_control_calamity_still_valid_at_vessel_turn_is_offered(tmp_path, monkeypatch):
    cold, jid, _ = game(tmp_path, monkeypatch, cl=3, profiles=[hazard()], profile_expires=100000,
                        ally_features=[], initiative={'enemy': 40, 'ally': 20, 'vessel': 0})
    service, table, mid = fight(cold, jid, tmp_path)
    assert clock(loaded(cold, mid)) == 4
    assert _offered(service, mid, FACE)
