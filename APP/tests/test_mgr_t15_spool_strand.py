"""Native Thread acquisition, owner scene inputs, committed handling and cold replay."""
from copy import deepcopy
import json
import zipfile
import pytest
from canonical_catalog.service import CanonicalCatalogAuthorityService
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet

PID, QID = '0badc0de-1400-4000-8000-000000000001', '0badc0de-1400-4000-8000-000000000002'
A, B = FACTORY_ACTOR_PREFIX + PID, FACTORY_ACTOR_PREFIX + QID


def game(tmp_path, monkeypatch, *, items=(), automatic=False):
    """Import a Path owner, acquire Thread at the table, then enter native travel."""
    base = sheet([], cl=5, name='Thread worker')
    base['identity'].update(proficiency_bonus=3, path_ids=['tianxia.path.qi_cultivation'])
    base['path_and_subpath'] = {'path_record_ids': ['tianxia.path.qi_cultivation']}
    base['equipment'] = [{'starting_kit': {'items': [{'item_id': item, 'quantity': 1} for item in items]}}]
    service = CombatService(ROOT, tmp_path)
    for pid in (PID, QID):
        path = service.combatant_library.install_root / pid / 'current.zip'
        path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(base))
    table = TabletopService(service, tmp_path)
    table.canonical_catalog = CanonicalCatalogAuthorityService(ROOT)
    table.add_advancement(PID, 'sphere', 'tianxia.sphere.thread')
    table.save_reactions(PID, {'mode': 'ask'})
    monkeypatch.setattr('combat.journey.secrets.token_hex', lambda n: '140000000000000000000001')
    arena = {'stable_id': 'material:field', 'display_name': 'Sewing worksite',
             'width_squares': 10, 'height_squares': 8, 'square_size_ft': 5,
             'starting_positions': {}, 'terrain_regions': []}
    monkeypatch.setattr(CombatService, 'factory_arenas', lambda self: {'field': deepcopy(arena)})
    state = service.create_journey(project_ids=[PID, QID], arena_id='field',
        positions={A: {'x': 1, 'y': 1}, B: {'x': 8, 'y': 1}}, base_paces={A: 1800, B: 1800},
        control_modes={A: 'LOCAL_AUTO' if automatic else 'MANUAL', B: 'MANUAL'})
    jid = state['journey_id']
    def cold():
        return CombatService(ROOT, tmp_path)
    def act(kind, payload=None, aid=A):
        fresh = cold()
        result = fresh.journey_act(jid, fresh.journey_state(jid)['revision'], aid, kind, payload)
        assert cold().journey_state(jid, viewer_id=aid) == result
        return result
    def admit(kind, payload, aid=A, gm=True):
        fresh = cold()
        return fresh.journey_admit(jid, fresh.journey_state(jid)['revision'], aid, kind, payload,
            gm=gm, reason='Scenario owner: actual sewing supplies and cloth workpieces, examined before handling.')
    return cold, jid, act, admit


def supply(admit, act, sid, kind, quantity, *, material=None, unit='portion'):
    admit('material_source', {'id': sid, 'name': sid.replace('-', ' ').title(),
        'kind': kind, 'context': 'scene', 'material': material or kind, 'unit': unit,
        'quantity': quantity, 'known_to': [A], 'exclusive_to': A})
    act('collect_material', {'source': sid, 'quantity': quantity})
    return sid + ':' + str(quantity)


from combat.ext.thread_handling import OPERATIONS, TOOLS, WORK_STATE, current_work
from combat.ext.thread_weaving import ORIGINS, QI_THREAD
from combat.ext.effect_durations import parse_round
from tests.test_a2_thread import settle
from tests.test_r4_integration import reach, candidate, send, auto_candidate
SOURCE = 'THREAD_BASE_SPOOL_AND_STRAND'
QI = 'resource:core.qi'


def task(admit, key, target, operation, *, difficult=False, dc=0):
    admit('thread_task', {'id':key, 'operation':operation, 'target':target,
          'difficulty':'difficult' if difficult else 'ordinary', 'dc':dc, 'ability':'DEX'})


def test_acquisition_all_ordinary_operations_real_tools_and_private_cold_replay(tmp_path, monkeypatch):
    cold, jid, act, admit = game(tmp_path, monkeypatch)
    actor = cold().journeys.load(jid).state['actors'][A]
    assert SOURCE in actor['bundle']['material_abilities']['owned']
    sheet_now = cold()._factory_owner_sheet(PID)
    assert SOURCE in sheet_now['spheres_and_talents']['automatic_sphere_component_record_ids']
    assert SOURCE not in sheet_now['spheres_and_talents']['learned_talent_record_ids']
    tools = [supply(admit, act, 'tool-'+name, 'thread_tool', 1, material=name) for name in TOOLS]
    before = actor['resources'][QI]
    for index, op in enumerate(OPERATIONS):
        workpiece = supply(admit, act, 'cloth-'+op, 'raw_material', 1, material='cloth')
        task(admit, op, workpiece, op)
        offered = cold().journey_menu(jid,A)['options']
        picked = next(r for r in offered if r['kind']=='thread_handle' and r['payload']['task']==op
                      and r['payload']['tool']==tools[index % len(tools)])
        result = act(picked['kind'],picked['payload'])
        own = result['actors'][A]
        assert own['thread_tasks'][op]['completed'] == 1
        assert own['material_holdings'][workpiece]['threadwork']['tool_id'] == tools[index % len(tools)]
        assert not any(r['kind']=='thread_handle' and r['payload']['task']==op
                       for r in cold().journey_menu(jid,A)['options'])
        with pytest.raises(ValueError,match='already completed'):
            act(picked['kind'],picked['payload'])
    state = cold().journeys.load(jid).state
    assert state['seconds']==0 and state['actors'][A]['resources'][QI]==before
    assert not any(e['kind']=='THREADWORK_CHECK' for e in state['events'])
    assert cold().journeys.replay(jid)['status']=='PASS'
    public = cold().journey_state(jid,B)
    assert 'material_sources' not in public and 'command_journal' not in public
    assert 'thread_tasks' not in public['actors'][A]
    assert 'material_holdings' not in public['actors'][A]
    assert not any(r['kind']=='thread_handle' for r in cold().journey_menu(jid,B)['options'])
    with pytest.raises(ValueError,match='learned'):
        task(lambda k,p: admit(k,p,aid=B), 'not-owner', 'missing', 'sew')


def test_difficult_requires_real_authorized_input_and_rolls_without_fabricated_success(tmp_path, monkeypatch):
    cold,jid,act,admit=game(tmp_path,monkeypatch)
    tool=supply(admit,act,'silk','thread_tool',1,material='silk')
    cloth=supply(admit,act,'cloth','raw_material',1,material='cloth')
    with pytest.raises(ValueError,match='Only the GM'):
        admit('thread_task',{'id':'difficult','operation':'sew','target':cloth,
              'difficulty':'difficult','dc':100,'ability':'DEX'},gm=False)
    task(admit,'difficult',cloth,'sew',difficult=True,dc=100)
    state=act('thread_handle',{'task':'difficult','tool':tool})
    assert not state['actors'][A]['thread_tasks']['difficult']['completed']
    checks=[e for e in state['events'] if e['kind']=='THREADWORK_CHECK']
    assert len(checks)==1 and checks[0]['roll']['total'] < 100
    assert 'threadwork' not in state['actors'][A]['material_holdings'][cloth]
    assert cold().journeys.replay(jid)['status']=='PASS'


def combat(cold,jid,tmp_path,maximum_rounds=20):
    state=cold().journeys.load(jid).state
    mid=cold().journey_start_combat(jid,state['revision'],{A:'team:a',B:'team:b'},
                                   maximum_rounds=maximum_rounds)['match_id']
    table=TabletopService(cold(),tmp_path)
    reach(table,mid,A)
    return table,mid


def test_independent_qi_all_origins_paid_refresh_natural_expiry_and_nonowner(tmp_path,monkeypatch):
    cold,jid,act,admit=game(tmp_path,monkeypatch,items=(
        'tianxia.mortal.weapon.jian','tianxia.mortal.gear.clothes_traveler_s'))
    bundle=cold().journeys.load(jid).state['actors'][A]['bundle']
    sleeve=next(i['key'] for i in bundle['carrying']['items'] if i['item_id']=='tianxia.mortal.gear.clothes_traveler_s')
    admit('thread_sleeve',{'item_key':sleeve})
    table,mid=combat(cold,jid,tmp_path)
    before=cold()._load_session(mid).engine.state.actors[A].resources[QI]
    for index,origin in enumerate(ORIGINS):
        settle(table,mid,candidate(table,mid,'Spool and Strand: Qi Thread from '+origin))
        session=cold()._load_session(mid)
        actor=session.engine.state.actors[A]
        strands=[c for c in actor.conditions.values() if c.condition_id==QI_THREAD]
        assert len(strands)==1 and strands[0].data['origin']==origin
        assert strands[0].source_actor_id==A and strands[0].data['origin_source']
        assert actor.resources[QI]==before-index-1
        assert parse_round(strands[0].expires_on)==(
            session.engine.state.round_number+10,session.engine.state.current_slot_index)
        assert all(type(v) in (str,int) for v in strands[0].data.values())
        assert session.mechanical.replay()['status']=='PASS'
    assert not any('spool.qi.' in x for x in session.engine.state.actors[B].action_ids)
    for _ in range(24):
        session=cold()._load_session(mid)
        if not any(c.condition_id==QI_THREAD for c in session.engine.state.actors[A].conditions.values()):
            break
        assert send(table,mid,table.state(mid)['menu']['end_turn'])['status']=='COMMITTED'
    else:
        raise AssertionError('Native strand expiry not reached')
    assert cold()._load_session(mid).mechanical.replay()['status']=='PASS'


def test_native_combat_ordinary_work_asks_player_commits_and_replays(tmp_path,monkeypatch):
    cold,jid,act,admit=game(tmp_path,monkeypatch)
    tool=supply(admit,act,'needle','thread_tool',1,material='needles')
    cloth=supply(admit,act,'sleeve-cloth','raw_material',1,material='cloth')
    task(admit,'hidden',cloth,'hide_spool')
    table,mid=combat(cold,jid,tmp_path,maximum_rounds=1)
    before=cold()._load_session(mid)
    balance=before.engine.state.actors[A].resources[QI]
    cid=candidate(table,mid,'Spool and Strand: hide spool')
    pending=send(table,mid,cid)
    assert pending['status']=='REACTION_REQUIRED'
    settle(table,mid,cid)
    session=cold()._load_session(mid)
    document=current_work(session.engine,session.engine.state.actors[A])
    assert document['holdings'][cloth]['threadwork']['concealed']==1
    assert document['tasks']['hidden']['completed']==1
    handling_logs=[e.payload for e in session.engine.events if e.event_type=='PASSIVE_TRIGGERED'
                   and '.spool.handle.hide_spool' in e.source_definition_id and 'log' in e.payload]
    assert handling_logs and all(p.get('history_hidden')==1 and 'Sleeve Cloth' not in p['log']
                                 for p in handling_logs)
    assert session.engine.state.actors[A].resources[QI]==balance
    assert not any(c.display_name=='Spool and Strand: hide spool' for c in session.engine.legal_candidates())
    assert session.mechanical.replay()['status']=='PASS'
    for _ in range(5):
        if cold()._load_session(mid).engine.state.terminal_result:
            break
        assert send(table,mid,table.state(mid)['menu']['end_turn'])['status']=='COMMITTED'
    assert cold()._load_session(mid).engine.state.terminal_result
    state=cold().journeys.load(jid).state
    resumed=cold().journey_resume(jid,state['revision'],
        effect_resolutions={A:'GM confirms the concealed threadwork has ended.'})
    # The stored snapshot is the leak source: without projection it still holds
    # the hidden threadwork document (workpieces, tools, tasks) for the actor.
    stored=cold().journeys.load(jid).state
    raw=next(e for e in stored['events'] if e['kind']=='ENCOUNTER_EFFECTS_RESOLVED')['previous_state']
    assert WORK_STATE in raw
    # The resume response is the same projected view every GET serves, never the
    # raw session (no replay genesis, command journal or private actor state).
    assert resumed==cold().journey_state(jid)
    assert 'replay_base' not in resumed and 'command_journal' not in resumed
    assert 'thread_tasks' not in resumed['actors'][A] and 'thread_facts' not in resumed['actors'][A]
    for viewer in (None,B):
        public=cold().journey_state(jid,viewer)
        receipt=next(e for e in public['events'] if e['kind']=='ENCOUNTER_EFFECTS_RESOLVED')
        assert WORK_STATE not in receipt['previous_state']
    actor=cold().journeys.load(jid).state['actors'][A]
    assert actor['material_holdings'][cloth]['threadwork']['concealed']==1
    assert actor['thread_tasks']['hidden']['completed']==1
    assert not any(WORK_STATE in row for row in actor['encounter_snapshot']['conditions'].values())


def test_scripture_preserves_ten_minutes_and_refresh_cost(tmp_path,monkeypatch):
    cold,jid,act,admit=game(tmp_path,monkeypatch)
    table=TabletopService(cold(),tmp_path)
    table.canonical_catalog=CanonicalCatalogAuthorityService(ROOT)
    table.add_advancement(PID,'talent','tianxia.talent.thread.qi_thread_scripture')
    # Journey already sealed its acquired sheet. Begin a new journey through the
    # actual finish/create path so the newly learned talent enters native combat.
    act('finish')
    monkeypatch.setattr('combat.journey.secrets.token_hex',lambda n:'150000000000000000000002')
    state=cold().create_journey(project_ids=[PID,QID],arena_id='field',
        positions={A:{'x':1,'y':1},B:{'x':8,'y':1}},base_paces={A:1800,B:1800})
    table,mid=combat(cold,state['journey_id'],tmp_path)
    settle(table,mid,candidate(table,mid,'Spool and Strand: Qi Thread from breath'))
    session=cold()._load_session(mid)
    strand=next(c for c in session.engine.state.actors[A].conditions.values() if c.condition_id==QI_THREAD)
    assert parse_round(strand.expires_on)==(session.engine.state.round_number+100,session.engine.state.current_slot_index)
    assert session.mechanical.replay()['status']=='PASS'


def test_scripture_multi_weapon_prompt_quotes_and_applies_ten_minutes(tmp_path,monkeypatch):
    # With two weapons the origin question has a real choice; Scripture's ten
    # minutes must be quoted there and then actually applied (F1 review).
    cold,jid,act,admit=game(tmp_path,monkeypatch,items=(
        'tianxia.mortal.weapon.jian','tianxia.mortal.weapon.dao'))
    table=TabletopService(cold(),tmp_path)
    table.canonical_catalog=CanonicalCatalogAuthorityService(ROOT)
    table.add_advancement(PID,'talent','tianxia.talent.thread.qi_thread_scripture')
    act('finish')
    monkeypatch.setattr('combat.journey.secrets.token_hex',lambda n:'150000000000000000000003')
    created=cold().create_journey(project_ids=[PID,QID],arena_id='field',
        positions={A:{'x':1,'y':1},B:{'x':8,'y':1}},base_paces={A:1800,B:1800})
    table,mid=combat(cold,created['journey_id'],tmp_path)
    cid=candidate(table,mid,'Spool and Strand: Qi Thread from weapon')
    result=send(table,mid,cid)
    assert result['status']=='REACTION_REQUIRED',result
    prompt=result['reaction']
    weapons=[o['id'] for o in prompt['choice']['options']]
    assert len(weapons)>1,prompt['choice']
    assert 'ten minutes' in prompt['moment'],prompt['moment']
    result=send(table,mid,cid,[{**prompt['context'],'selection':'USE','option_ids':[weapons[0]]}])
    assert result['status']=='COMMITTED',result
    session=cold()._load_session(mid)
    strand=next(c for c in session.engine.state.actors[A].conditions.values() if c.condition_id==QI_THREAD)
    assert strand.data['origin']=='weapon' and strand.data['origin_source']==weapons[0]
    assert parse_round(strand.expires_on)==(session.engine.state.round_number+100,session.engine.state.current_slot_index)
    assert session.mechanical.replay()['status']=='PASS'


def test_automatic_owner_uses_only_own_work_and_normal_handling_defaults_no_check(tmp_path, monkeypatch):
    cold,jid,act,admit=game(tmp_path,monkeypatch,automatic=True)
    tool=supply(admit,act,'own-cord','thread_tool',1,material='cord')
    cloth=supply(admit,act,'own-cloth','raw_material',1,material='cloth')
    # No artificial difficulty selector is needed for ordinary handling.
    admit('thread_task',{'id':'normal','operation':'tie_knot','target':cloth})
    option=next(r for r in cold().journey_menu(jid,A)['options'] if r['kind']=='thread_handle')
    assert option['auto_select']==1 and option['payload']['tool']==tool
    state=cold().journey_auto_step(jid,cold().journey_state(jid)['revision'],A,option['id'])
    assert state['actors'][A]['thread_tasks']['normal']['completed']==1
    assert not any(e['kind']=='THREADWORK_CHECK' for e in state['events'])
    assert cold().journeys.replay(jid)['status']=='PASS'
    task(admit,'combat-normal',cloth,'control')
    table,mid=combat(cold,jid,tmp_path)
    # An automatic seat's table menu is trimmed to its routing keys, so the
    # offered candidate is read from the engine's own legal candidates instead.
    cid=next(c.candidate_id for c in cold()._load_session(mid).engine.legal_candidates()
             if c.display_name=='Spool and Strand: control')
    # Deterministic fake primary controller; reactions retain the native
    # automatic-choice adapter. No live model transport is used.
    auto_candidate(table.combat,mid,A,cid)
    result=table.auto_step(mid,0)
    assert result['status']=='COMMITTED'  # automatic owner supplies its own Needle answer
    session=cold()._load_session(mid)
    own=current_work(session.engine,session.engine.state.actors[A])
    assert own['tasks']['combat-normal']['completed']==1
    assert session.mechanical.replay()['status']=='PASS'


def test_act_response_is_the_acting_seat_projection_not_raw_state(tmp_path, monkeypatch):
    cold, jid, act, admit = game(tmp_path, monkeypatch)
    admit('material_source', {'id': 'own-cord', 'name': 'Own cord', 'kind': 'thread_tool', 'context': 'scene',
        'material': 'cord', 'unit': 'portion', 'quantity': 2, 'known_to': [A], 'exclusive_to': A})
    result = act('collect_material', {'source': 'own-cord', 'quantity': 1})
    for hidden in ('replay_base', 'command_journal', 'material_sources'):
        assert hidden not in result
    assert result == cold().journey_state(jid, viewer_id=A)


def test_refused_admission_writes_nothing(tmp_path, monkeypatch):
    cold,jid,act,admit=game(tmp_path,monkeypatch)
    before=cold().journey_state(jid)
    with pytest.raises(ValueError,match='Only the GM'):
        admit('material_source',{'id':'unauthorized','name':'Unauthorized','kind':'raw_material',
              'context':'field','material':'cloth','unit':'portion','quantity':1,'known_to':[A]},gm=False)
    assert cold().journey_state(jid)==before


def test_returning_owner_second_journey_keeps_shared_sources_and_menu(tmp_path, monkeypatch):
    """F12: a Thread owner's tool and open work must survive into a second journey.

    material_sources is shared (journey_shared_fields); save() must persist it at the registry's
    top level, or the next journey loses the source row and journey_menu raises KeyError.
    """
    cold, jid, act, admit = game(tmp_path, monkeypatch)
    supply(admit, act, 'needle', 'thread_tool', 1, material='needles')
    cloth = supply(admit, act, 'cloth', 'raw_material', 1, material='cloth')
    task(admit, 'open-sew', cloth, 'sew')
    assert any(r['kind'] == 'thread_handle' and r['payload']['task'] == 'open-sew'
               for r in cold().journey_menu(jid, A)['options'])
    act('finish', {})
    monkeypatch.setattr('combat.journey.secrets.token_hex', lambda n: '140000000000000000000002')
    second = cold().create_journey(project_ids=[PID, QID], arena_id='field',
        positions={A: {'x': 1, 'y': 1}, B: {'x': 8, 'y': 1}}, base_paces={A: 1800, B: 1800},
        control_modes={A: 'MANUAL', B: 'MANUAL'})
    jid2 = second['journey_id']
    assert jid2 != jid
    shared = cold().journeys.load(jid2).state['material_sources']
    assert {'needle', 'cloth'} <= set(shared)
    options = cold().journey_menu(jid2, A)['options']
    assert any(r['kind'] == 'thread_handle' and r['payload']['task'] == 'open-sew'
               and r['payload']['tool'] == 'needle:1' for r in options)
