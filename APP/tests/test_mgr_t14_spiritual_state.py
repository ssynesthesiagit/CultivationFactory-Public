"""Native sheets, journey declarations, table intents and cold mechanical replay.

No fabricated ownership, condition, Measure, Favor, String or Satiety receipts.
Only the owner input surface and deterministic dice are controlled.
"""
from copy import deepcopy
import json
import pytest

from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.tabletop_service import TabletopService
from combat.gate2_rolls import DeterministicRollAuthority
from combat.tabletop import normalize_map, to_battlefield
from combat.ext import spiritual_state as ss
from combat.ext.ancestral_channeler import POSSESSION, COUNCIL, CHANNELER_SOURCE, POSTURE
from combat.ext.seraphic_molter import WINGS, WINGS_OUT, BEAT, GLIDE, PINIONS
from combat.ext.boundary_passage import DENY
from combat.ext.soulstring_dancer import THREADED, STRING
from combat.ext.equal_measure_scripture import RECEIVE, RECOMPENSE, POOL
from tests.h1_support import ROOT, sheet

OWNER_PROJECT, OTHER_PROJECT = ('face0000-0000-4000-8000-000000000001', 'face0000-0000-4000-8000-000000000002')
A, B = [FACTORY_ACTOR_PREFIX + x for x in (OWNER_PROJECT, OTHER_PROJECT)]
SPIKE = 'tianxia.path.spirit_awakening.feature.mind_spike'
RES = 'resource:core.resonance'
SPIRIT_PATH = 'tianxia.path.spirit_awakening'
_ACQUIRED = None
AXE = {'starting_kit': {'items': [{'item_id': 'tianxia.mortal.weapon.fu',
                                 'name': 'Fu (Short Axe)', 'quantity': 1}]}}


@pytest.fixture(scope='module', autouse=True)
def spirit_acquisition(tmp_path_factory):
    """Acquire through authenticated native events, then cold-read parent rows.

    The test pack seals the shipped authority projections; it grants no actor
    a feature. Public project authority records exact Method/access/AP events,
    and NS1R validates these before the compiler may grant the progression.
    """
    from app.core import Database, Settings
    from project_store.service import ProjectStore
    from non_sphere_authority import NonSphereAuthorityService
    from tests.ns1r_evidence_helpers import install_authority_test_pack, TEST_PACK_ID, TEST_PACK_VERSION
    settings = Settings.from_env(ROOT, tmp_path_factory.mktemp('spirit-native-acquisition'))
    settings.ensure_dirs()
    # Explicit runtime data dependencies are part of this native test pack.
    # The compiler dynamically globs these splits; an exporter omitting them
    # must fail before presenting missing ownership as a combat result.
    for dependency in (ROOT / 'combat/rules/feature_blocks.d/riders_c8.json',
                       ROOT / 'combat/rules/feature_blocks.d/auto_H1.json',
                       ROOT / 'combat/rules/feature_blocks.d/a2_misc_subpaths_3.json'):
        assert json.loads(dependency.read_text())['features'], f'Native Spirit test pack lacks {dependency.name}'
    db = Database(settings)
    db.migrate()
    service = NonSphereAuthorityService(db)
    install_authority_test_pack(db, service)
    documents = {}
    def project(cl):
        store = ProjectStore(db)
        pid = store.create_project(working_name='Native spiritual acquisition',
            pack_locks=[{'pack_id': TEST_PACK_ID, 'version': TEST_PACK_VERSION}],
            user_locks=[{'field':'target_cl','value':cl}])['project']['project_id']
        store.add_server_locked_records(pid, [service.project_locked_method_catalog_record('METHOD-005')])
        method = service.commit_authority_event(pid, 'method_access', {'method_id':'METHOD-005'},
            idempotency_key=pid+'-method-access')['evidence_id']
        service.initialize_for_project(pid, target_cl=cl, path_ids=[SPIRIT_PATH], method_id='METHOD-005',
            access_source_records=[method])
        if cl > 1:
            earned = service.commit_authority_event(pid,'ap_award',{'method_id':'METHOD-005','target_cl':cl},
                amount_awarded=cl-1,idempotency_key=pid+'-earned-ap')['evidence_id']
            service.allocate_advancement(pid,{SPIRIT_PATH:cl-1},evidence_id=earned,idempotency_key=pid+'-advance')
        return pid
    def acquire(cl, tradition):
        key = (cl, tradition)
        if key not in documents:
            pid = project(cl)
            access = service.commit_authority_event(pid,'subpath_access',
                {'selection_id':tradition,'path_id':SPIRIT_PATH},idempotency_key=pid+'-tradition-access')['evidence_id']
            service.select_subpath(pid,SPIRIT_PATH,tradition,access_source_records=[access])
            state = NonSphereAuthorityService(db).get_state(pid)
            assert next(row for row in state['paths'] if row['path_id'] == SPIRIT_PATH)['subpath_or_tradition_id'] == tradition
            documents[key] = state['paths']
        return deepcopy(documents[key])
    acquire.service, acquire.project = service, project
    global _ACQUIRED
    _ACQUIRED = acquire
    yield acquire
    _ACQUIRED = None


def settle(table, mid, candidate_id, picks=None, *, auto=False):
    """Commit through the public table API, preserving each player's choices.

    Keep this driver local: unrelated historical test fixtures are neither
    prerequisites nor data sources for these native spiritual-state cases.
    """
    answers, prompts, seen = [], [], {}
    for _ in range(20):
        menu = table.state(mid)['menu']
        result = (table.auto_step(mid, 0, answers) if auto else
                  table.act(mid, candidate_id, menu['decision_id'], menu['state_version'], 0, answers))
        if result['status'] != 'REACTION_REQUIRED':
            assert result['status'] == 'COMMITTED', result
            return prompts
        prompt = result['reaction']
        prompts.append(prompt)
        source = prompt['context']['reaction_source_id']
        choice = (picks or {}).get(source, 'first' if source.startswith('choice:') else None)
        count = seen.get(source, 0)
        seen[source] = count + 1
        if isinstance(choice, tuple):
            choice = choice[min(count, len(choice) - 1)]
        answer = {**prompt['context'], 'selection': 'USE' if choice is not None else 'DECLINE'}
        if choice is not None and prompt.get('choice'):
            answer['option_ids'] = ([o['id'] for o in prompt['choice']['options'][:max(1, prompt['choice'].get('minimum_selections', 1))]] if choice == 'first'
                                    else choice if isinstance(choice, list) else [choice])
        answers.append(answer)
    raise AssertionError('Too many prompts')


def entry(value, cl=10):
    return {'value': value, 'source_cl': cl, 'ruling': 'Explicit source-scoped table declaration for this scene.'}


def test_native_acquisition_requires_exact_access_parent_and_available_tier(spirit_acquisition):
    from app.core import FoundryError
    from combat.factory_compiler import compile_character
    tradition = THREADED.split('.feature.')[0]
    project = spirit_acquisition.project(10)
    with pytest.raises(FoundryError) as missing:
        spirit_acquisition.service.select_subpath(project, SPIRIT_PATH, tradition)
    assert missing.value.code == 'NS1R_RESTRICTED_TRADITION_ACCESS_REQUIRED'
    with pytest.raises(FoundryError) as wrong:
        spirit_acquisition.service.select_subpath(project, 'tianxia.path.qi_cultivation', tradition)
    assert wrong.value.code == 'NS1R_PATH_SUBPATH_MISMATCH'
    document = sheet([], cl=10, primary='Resonance', key='WIS')
    document['path_and_subpath'] = {'paths': spirit_acquisition(10, tradition)}
    native = compile_character(document, actor_id=A)
    assert any(row.get('feature_id') == THREADED for row in native['typed_passives'])
    assert native['spiritual_path_cl'] == 10
    wisdom = next(row['modifier'] for row in document['ability_scores_and_statistics']['abilities'] if row['ability'] == 'WIS')
    assert native['spiritual_path_numbers']['save_dc'] == 8 + 4 + wisdom
    assert native['spiritual_path_numbers']['save_dc'] != document['ability_scores_and_statistics']['technique_save_dc']
    owning = next(row for row in document['path_and_subpath']['paths'] if row['path_id'] == SPIRIT_PATH)
    owning['effective_cl'] = True
    with pytest.raises(ValueError, match='integer effective CL'):
        compile_character(document, actor_id=A)
    owning['effective_cl'] = 10
    owning['key_ability'] = 'CHA'
    with pytest.raises(ValueError, match='printed fixed key'):
        compile_character(document, actor_id=A)
    del owning['key_ability']
    # A stale exported occurrence cannot reopen a tier suppressed by its
    # actual owning Path; this is a negative admission guard, not acquisition.
    next(row for row in document['path_and_subpath']['paths'] if row['path_id'] == SPIRIT_PATH)['effective_cl'] = 2
    document['path_and_subpath']['source_granted_subpath_feature_record_ids'] = [THREADED]
    suppressed = compile_character(document, actor_id=A)
    assert not any(row.get('feature_id') == THREADED for row in suppressed['typed_passives'])
    ancestor = sheet([], cl=10, primary='Resonance', key='WIS')
    ancestor['path_and_subpath'] = {'paths': spirit_acquisition(6, COUNCIL.split('.feature.')[0])}
    ancestor[ss.KEY] = {'covenant': covenant()}
    with pytest.raises(ValueError, match='third Ancestor Office requires CL10'):
        compile_character(ancestor, actor_id=A)
    ancestor['path_and_subpath']['paths'] = spirit_acquisition(10, COUNCIL.split('.feature.')[0])
    next(row for row in ancestor['path_and_subpath']['paths'] if row['path_id'] == SPIRIT_PATH)['effective_cl'] = 2
    retained = compile_character(ancestor, actor_id=A)
    assert retained[ss.KEY]['covenant']['offices'] == covenant()['offices']
    assert not any(row.get('feature_id') == POSSESSION for row in retained['typed_passives'])


def covenant():
    return {'membership': 'Accepted by the Hall of Reed', 'duty': 'Protect the burial archive',
            'taboo': 'Never burn a named ancestor record', 'ordinary_restitution': 'Repair the archive',
            'severe_restitution': 'Recover the lost archive', 'offices': ['Warrior', 'Healer','Wayfarer'],
            'knowledge_domains': ['Reed Hall', 'Burial rites', 'Northern march']}


def game(tmp_path, monkeypatch, features=(), *, other=(SPIKE,), owner_record=None, other_record=None,
         cl=10, dc=60, size='Medium', other_cl=None, speed=30, kit=None, check_results=None,
         modes=None, maximum_rounds=20, return_journey=False, positions=None, lineage_acts=(), attack_natural=15, save_results=None,
         covenant_upgrade=None, activity=False, solo=False, surfaces=None, columns=()):
    def owner_sheet(self, pid):
        selected = features if pid == OWNER_PROJECT else other
        document = sheet([feature for feature in selected if not feature.startswith('tianxia.tradition.spirit.')],
                         cl=cl if pid == OWNER_PROJECT else other_cl or cl, dc=dc,
                         name='Spirit owner' if pid == OWNER_PROJECT else 'Spirit other', primary='Resonance', key='WIS', kit=kit)
        document['identity']['path'] = 'Spirit Awakening'
        document['identity']['proficiency_bonus'] = 2 + ((cl if pid == OWNER_PROJECT else other_cl or cl)-1)//4
        traditions = {feature.split('.feature.')[0] for feature in (features if pid == OWNER_PROJECT else other)
                      if feature.startswith('tianxia.tradition.spirit.')}
        assert len(traditions) <= 1, 'The canonical Path grants one normal Subpath progression.'
        if traditions:
            assert _ACQUIRED is not None
            document.setdefault('path_and_subpath',{})['paths'] = _ACQUIRED(
                cl if pid == OWNER_PROJECT else other_cl or cl, next(iter(traditions)))
        document['ability_scores_and_statistics']['hit_points']['maximum'] = 500
        if pid != OWNER_PROJECT:
            document['identity']['size'] = size
        else:
            document['ability_scores_and_statistics']['speed']['walking_ft'] = speed
        return document
    monkeypatch.setattr(CombatService, '_factory_owner_sheet', owner_sheet)
    arena = to_battlefield(normalize_map({'display_name': 'Spirit yard', 'width_squares': 12, 'height_squares': 12,
        **({'surfaces':surfaces} if surfaces is not None else {}),
        'walls': [], 'objects': [{'id': 1, 'kind': 'door', 'name': 'Burial gate', 'x': 4, 'y': 6,
            'mount_axis': 'h', 'mount_line': 600, 'interaction': 'simple_door', 'door_open': 1}]}))
    for index, (x, y, height) in enumerate(columns):
        arena['terrain_regions'].append({'region_id':'raised-column-'+str(index), 'terrain_type':'BLOCKED',
            'movement_cost':0, 'description':'Recorded finite stone column', 'cells':[{'x':x,'y':y}], 'height_ft':height})
    monkeypatch.setattr(CombatService, 'factory_arenas', lambda self, **kwargs: {'spirit-yard': arena})
    original = DeterministicRollAuthority.raw_d20
    save_bindings = {}
    def dice(self, **kwargs):
        roll = original(self, **kwargs)
        natural = 1 if kwargs['reason'].startswith(('SAVE:', 'CHECK:')) else attack_natural
        if save_results and kwargs['reason'].startswith('SAVE:'):
            selected = save_results.get(kwargs['actor_id'],natural)
            if isinstance(selected,list):
                key = (kwargs['actor_id'],roll.roll_id)
                if key not in save_bindings:
                    index = sum(actor == kwargs['actor_id'] for actor,_roll in save_bindings)
                    save_bindings[key] = selected[min(index,len(selected)-1)]
                natural = save_bindings[key]
            else:
                natural = selected
        if check_results and kwargs['reason'].startswith('CHECK:'):
            natural = check_results.get(kwargs['actor_id'], natural)
        return roll.model_copy(update={'dice': (natural,), 'natural_result': natural, 'total': natural + kwargs['modifier']})
    monkeypatch.setattr(DeterministicRollAuthority, 'raw_d20', dice)
    cold = lambda: CombatService(ROOT, tmp_path)
    party = [A] if solo else [A, B]
    state = cold().create_journey(project_ids=[OWNER_PROJECT] if solo else [OWNER_PROJECT, OTHER_PROJECT], arena_id='spirit-yard',
        positions=positions or {aid: {'x': 3 if aid == A else 4, 'y': 6} for aid in party}, base_paces={aid:30 for aid in party},
        control_modes=modes or {aid:'MANUAL' for aid in party})
    jid = state['journey_id']
    for aid, record in ((A, owner_record), (B, other_record)):
        if record is not None:
            if record.get('covenant'):
                service = cold()
                state = service.journey_act(jid, service.journey_state(jid)['revision'], aid,
                    'record_spiritual_state', {'record': {'covenant': deepcopy(record['covenant'])}})
            world, subjective = {}, {}
            for source, facts in record.get('facts', {}).items():
                for name, value in facts.items():
                    destination = subjective if name == 'willing' else world
                    destination.setdefault(source, {})[name] = deepcopy(value)
            for facts, kind in ((world, ss.WORLD_INPUT), (subjective, ss.SUBJECT_INPUT)):
                # Each fact has its own reader set; a public host relation
                # must not make an unrelated private dispute public too.
                entries = [(source, name, value) for source, fields in facts.items() for name, value in fields.items()]
                entries.sort(key=lambda item: item[1] == 'host_id')
                for source, name, value in entries:
                    payload = {'source': ss.INPUT_SOURCE, 'subject': aid, 'kind': kind,
                        'scope': ss.input_scope(source, name), 'value': {'facts': {source: {name: value}}},
                        'expires_at': 86400, 'readers': [A, B] if value.get('visibility') == 'public' else value.get('known_to', [])}
                    service = cold()
                    revision = service.journey_state(jid)['revision']
                    state = (service.journey_world_fact(jid, revision, payload) if kind == ss.WORLD_INPUT else
                             service.journey_act(jid, revision, aid, 'declare_fact', payload))
            assert cold().journey_state(jid) == state
    for act in lineage_acts:
        state = cold().journey_world_fact(jid,cold().journey_state(jid)['revision'], {
            'source':ss.INPUT_SOURCE,'subject':A,'kind':ss.LINEAGE_INPUT,
            'scope':ss.input_scope(ss.CHANNELER,'lineage_act:'+act['act_id']),
            'value':deepcopy(act),'expires_at':86400,'readers':[]})
        assert cold().journey_state(jid) == state
    if covenant_upgrade is not None:
        state = cold().journey_act(jid, cold().journey_state(jid)['revision'], A,
            'record_spiritual_state', {'record': {'covenant': deepcopy(covenant_upgrade)}})
        assert cold().journey_state(jid) == state
    if activity:
        return cold, None, None, jid
    mid = cold().journey_start_combat(jid, cold().journey_state(jid)['revision'], {A: 'team:a', B: 'team:b'}, maximum_rounds=maximum_rounds)['match_id']
    if return_journey:
        return cold, TabletopService(cold(), tmp_path), mid, jid
    return cold, TabletopService(cold(), tmp_path), mid


def engine(cold, mid):
    session = cold()._load_session(mid)
    assert session.verify()['status'] == 'PASS'
    assert session.mechanical.replay()['status'] == 'PASS'
    return session.engine


def test_native_covenant_adds_only_its_printed_third_office_without_rewriting_obligations(tmp_path, monkeypatch):
    original = covenant()
    original['offices'] = ['Warrior', 'Archivist']
    advanced = {**deepcopy(original), 'offices': ['Warrior', 'Archivist', 'Ritualist'],
                'ritual_proficiency': 'herbalism kit'}
    cold, table, mid = game(tmp_path/'legal', monkeypatch, [COUNCIL, POSSESSION],
        owner_record={'covenant': original}, covenant_upgrade=advanced)
    assert ss.read(engine(cold, mid).state.actors[A])['covenant'] == advanced
    with pytest.raises(ValueError, match='covenant obligations and Offices persist'):
        game(tmp_path/'invalid', monkeypatch, [COUNCIL, POSSESSION],
            owner_record={'covenant': original}, covenant_upgrade={**advanced, 'taboo':'Ignore the old taboo'})


def test_native_unknown_covenant_does_not_invent_offices_or_spend_possession_cost(tmp_path, monkeypatch):
    cold, table, mid = game(tmp_path, monkeypatch, [COUNCIL, POSSESSION])
    turn(table, mid, B)
    current, prompts = play(cold, table, mid, 'Mind Spike', A)
    assert not any(prompt['context']['reaction_source_id'] == POSSESSION for prompt in prompts)
    assert not ss.read(current.state.actors[A]).get('covenant')
    assert current.state.actors[A].resources[RES] == 30
    assert not any(condition.condition_id == POSTURE and condition.source_definition_id == POSSESSION
                   for condition in current.state.actors[A].conditions.values())


def turn(table, mid, aid, picks=None):
    for _ in range(12):
        state = table.state(mid)
        if state['menu']['actor_id'] == aid:
            return
        settle(table, mid, state['menu']['end_turn'], picks)
    raise AssertionError('No requested turn')


def play(cold, table, mid, name, target=None, picks=None, at=None):
    setup_prompts = []
    if cold()._load_session(mid).engine.state.setup_tasks:
        setup = next(c for c in cold()._load_session(mid).engine.legal_candidates()
                     if c.source_definition_id == 'system:combat.fight_setup')
        setup_prompts = settle(table, mid, setup.candidate_id, picks)
    rows = cold()._load_session(mid).engine.legal_candidates()
    candidate = next((c for c in rows if c.display_name == name and (target is None or c.target_ids == (target,))
                      and (at is None or c.destination and (c.destination.x,c.destination.y,c.destination.z) == at)), None)
    assert candidate is not None, (name, sorted({c.display_name for c in rows}))
    prompts = settle(table, mid, candidate.candidate_id, {POSSESSION: 'first',
        'choice:needle.equal_measure.measured_return':None, **(picks or {})})
    return engine(cold, mid), setup_prompts + prompts


def activity_act(cold, jid, actor_id, candidate_id, picks=None):
    state = cold().journey_state(jid)
    procedure = isinstance(candidate_id, dict)
    state = cold().journey_act(jid, state['revision'], actor_id,
        'native_procedure' if procedure else 'native_activity',
        candidate_id if procedure else {'candidate_id':candidate_id})
    prompts = []
    for _ in range(24):
        pending = state.get('native_activity_pending')
        if pending is None:
            return state, prompts
        request = pending['request']
        prompts.append(request)
        spec = request.get('extension_choice') or {}
        ids = list(dict.fromkeys([*spec.get('preferred', []), *request.get('legal_option_ids', []), *spec.get('option_ids', [])]))
        source = request['reaction_source_id']
        selection = (picks or {}).get(source, 'first' if source.startswith('choice:') else None)
        chosen = ids[:max(1, spec.get('minimum_selections', 1))] if selection == 'first' else [] if selection is None else [selection]
        answer = {key:request[key] for key in ('checkpoint','reactor_id','reaction_source_id')}
        answer.update(selection='USE' if selection is not None else 'DECLINE', option_ids=chosen)
        state = cold().journey_act(jid, state['revision'], request['reactor_id'], 'native_activity_answer', answer)
        assert cold().journey_state(jid) == state
    raise AssertionError('Native activity choices did not settle')


@pytest.mark.parametrize('natural,violated,exception,expected_strain,incapacitated,use_possession', [
    (1, 0, 'none', True, False, False), (20, 0, 'none', False, False, False),
    (20, 1, 'none', True, False, False), (20, 1, 'complete_soul_destruction', False, False, False),
    (1, 0, 'none', True, True, False), (1, 0, 'none', True, False, True),
])
def test_native_ancestor_withdrawal_produces_strain_and_only_its_one_hour_rite_removes_it(
        tmp_path, monkeypatch, natural, violated, exception, expected_strain, incapacitated, use_possession):
    from combat.ext.lineage_reconciliation import ASCENSION, PRESENCE, STRAIN, REQUEST, REVIEW_SOURCE, REVIEW_KIND
    from combat.ext.forged_exhaustion import level
    from combat.journey_activity import load, replay_record
    cold, _, _, jid = game(tmp_path, monkeypatch, [ASCENSION], cl=18, activity=True, solo=True,
        owner_record={'covenant': covenant()}, save_results={A: natural})
    native = load(cold().journeys.load(jid))
    assert not any(row['kind'] == 'native_procedure' for row in cold().journey_menu(jid, A)['options'])
    activate = next(c for c in native.legal_candidates() if any(
        row.get('type') == 'ancestral_ascend' and row.get('office') == 'Warrior'
        for row in native.action_catalog[c.source_definition_id].parameters.get('typed', {}).get('effects', [])))
    state, _ = activity_act(cold, jid, A, activate.candidate_id)
    state = cold().journey_act(jid, state['revision'], A, 'native_activity_end', {})
    presence_id = next(key for key, raw in state['actors'][A]['encounter_snapshot']['conditions'].items()
                       if json.loads(raw)['condition_id'] == PRESENCE)
    scene = state['scene_id']
    state = cold().journey_end_scene(jid, state['revision'], 'The ancestor’s scene has ended.')
    assert state['scene_id'] == scene and state[REQUEST]['scene_id'] == scene
    payload = {'source': REVIEW_SOURCE, 'subject': A, 'kind': REVIEW_KIND, 'scope': presence_id,
        'value': {'violated': violated, 'sole_available_way': int(exception != 'none'),
            'exception': exception, 'acts': 'The actual accepted presence guarded the named lineage archive.',
            'ruling': 'The table reviewed the ancestor’s actual activation against the recorded covenant.'},
        'expires_at': int(state['seconds']) + 3600, 'readers': []}
    with pytest.raises(ValueError):
        cold().journey_act(jid, state['revision'], A, 'declare_fact', payload)
    with pytest.raises(ValueError):
        cold().journey_world_fact(jid, state['revision'], {**payload, 'scope': 'invented-presence'})
    with pytest.raises(ValueError):
        cold().journey_world_fact(jid, state['revision'], {**payload, 'value': {**payload['value'],
            'violated': 1, 'sole_available_way': 1, 'exception': 'higher_ranked_duty'}})
    state = cold().journey_world_fact(jid, state['revision'], payload)
    if incapacitated:
        # The existing native journey declaration supplies the external health
        # circumstance; no direct ActorState mutation or fabricated receipt.
        state = cold().journey_act(jid, state['revision'], A, 'incapacitated', {'value': True})
    ending = next(row for row in cold().journey_menu(jid, A)['options'] if row['kind'] == 'native_procedure')
    before_withdrawal_clock = state['seconds']
    before_withdrawal_resonance = state['actors'][A]['resources'][RES]
    state, prompts = activity_act(cold, jid, A, ending['payload'],
        {POSSESSION: 'first', 'choice:needle.ancestral.possession_payment': 'resonance'} if use_possession else None)
    assert state['seconds'] == before_withdrawal_clock and not state.get('native_activity')
    committed = next(e for e in reversed(state['events']) if e['kind'] == 'NATIVE_ACTIVITY_COMMITTED')
    replayed = replay_record(committed)
    assert any(c.condition_id == STRAIN for c in replayed.actors[A].conditions.values()) is expected_strain
    assert level(replayed.actors[A]) == int(expected_strain)
    assert bool(ss.disputed(replayed.actors[A])) is expected_strain
    assert not any(c.condition_id == PRESENCE for c in replayed.actors[A].conditions.values())
    cold_actor = load(cold().journeys.load(jid)).state.actors[A]
    assert cold_actor.resources == replayed.actors[A].resources
    assert cold_actor.current_hp == replayed.actors[A].current_hp
    assert any(c.condition_id == STRAIN for c in cold_actor.conditions.values()) is expected_strain
    assert level(cold_actor) == int(expected_strain)
    if use_possession:
        assert any(prompt['reaction_source_id'] == POSSESSION for prompt in prompts)
        assert replayed.actors[A].resources[RES] == before_withdrawal_resonance - 2
        assert any(c.condition_id == POSTURE and c.source_definition_id == POSSESSION
                   for c in replayed.actors[A].conditions.values())
        assert not any(c.condition_id == POSTURE and c.source_definition_id == POSSESSION
                       for c in cold_actor.conditions.values()), 'The upcoming unstarted turn is now, not a new round away.'
    state = cold().journey_end_scene(jid, state['revision'], 'The reviewed ancestor withdrew.')
    assert state['scene_id'] != scene and REQUEST not in state
    if expected_strain:
        before_clock, before_resources = state['seconds'], dict(state['actors'][A]['resources'])
        if incapacitated:
            with pytest.raises(ValueError):
                cold().journey_act(jid, state['revision'], A, 'lineage_reconciliation', {})
            assert cold().journey_state(jid) == state
            return
        state = cold().journey_act(jid, state['revision'], A, 'lineage_reconciliation', {})
        assert state['seconds'] == before_clock + 3600
        assert state['actors'][A]['resources'] == before_resources
        assert not any(json.loads(raw)['condition_id'] == STRAIN
                       for raw in state['actors'][A]['encounter_snapshot']['conditions'].values())
        restored = load(cold().journeys.load(jid)).state.actors[A]
        assert not ss.disputed(restored) and level(restored) == 1
        with pytest.raises(ValueError):
            cold().journey_act(jid, state['revision'], A, 'lineage_reconciliation', {})


def test_native_scene_without_accepted_ancestor_has_no_withdrawal_or_reconciliation(tmp_path, monkeypatch):
    from combat.ext.lineage_reconciliation import REQUEST, ASCENSION, ENDING
    cold, _, _, jid = game(tmp_path, monkeypatch, [POSSESSION], activity=True,
        owner_record={'covenant': covenant()})
    state = cold().journey_state(jid)
    scene = state['scene_id']
    state = cold().journey_end_scene(jid, state['revision'], 'No ancestor is ascended here.')
    assert state['scene_id'] != scene and REQUEST not in state
    assert not any(row['kind'] == 'lineage_reconciliation' for row in cold().journey_menu(jid, A)['options'])
    with pytest.raises(ValueError):
        cold().journey_act(jid, state['revision'], B, 'lineage_reconciliation', {})
    for actor, source in ((B, ASCENSION), (A, 'system:unregistered')):
        with pytest.raises(ValueError):
            cold().journey_act(jid, state['revision'], actor, 'native_procedure', {'source': source, 'procedure': ENDING})
        assert cold().journey_state(jid) == state


def test_native_accepted_ancestor_keeps_office_authority_reachable(tmp_path, monkeypatch):
    from combat.ext.lineage_reconciliation import ASCENSION
    from combat.journey_activity import load, replay_record
    cold, _, _, jid = game(tmp_path, monkeypatch, [ASCENSION], cl=18, activity=True,
        owner_record={'covenant': covenant()})
    state = cold().journey_state(jid)
    state = cold().journey_world_fact(jid, state['revision'], {
        'source': 'system:journey.activity', 'subject': A, 'kind': 'relations', 'scope': jid,
        'value': {'actors': {min(A, B): {max(A, B): 'ENEMY'}}}, 'expires_at': 86400, 'readers': [A, B]})
    native = load(cold().journeys.load(jid))
    activate = next(c for c in native.legal_candidates() if any(
        row.get('type') == 'ancestral_ascend' and row.get('office') == 'Warrior'
        for row in native.action_catalog[c.source_definition_id].parameters.get('typed', {}).get('effects', [])))
    state, _ = activity_act(cold, jid, A, activate.candidate_id)
    native = load(cold().journeys.load(jid))
    options = native.legal_candidates()
    authority = next(c for c in options if native.action_catalog.get(c.source_definition_id)
        and native.action_catalog[c.source_definition_id].parameters.get('ancestral_authority') == 'Warrior')
    assert authority.target_ids == (B,)
    state, _ = activity_act(cold, jid, A, authority.candidate_id)
    committed = next(e for e in reversed(state['events']) if e['kind'] == 'NATIVE_ACTIVITY_COMMITTED')
    assert load(cold().journeys.load(jid)).state.model_dump(mode='json') == replay_record(committed).model_dump(mode='json')


def test_native_ascension_recast_remains_legal_and_resolves_old_withdrawal_before_new_office(tmp_path, monkeypatch):
    from combat.ext.lineage_reconciliation import ASCENSION, PRESENCE, STRAIN, REVIEW_SOURCE, REVIEW_KIND
    from combat.journey_activity import load, replay_record
    cold, _, _, jid = game(tmp_path, monkeypatch, [ASCENSION], cl=18, activity=True, solo=True,
        owner_record={'covenant': covenant()}, save_results={A: 1})
    def option(office):
        native = load(cold().journeys.load(jid))
        return next(c for c in native.legal_candidates() if any(
            row.get('type') == 'ancestral_ascend' and row.get('office') == office
            for row in native.action_catalog[c.source_definition_id].parameters.get('typed', {}).get('effects', [])))
    state, _ = activity_act(cold, jid, A, option('Warrior').candidate_id)
    state = cold().journey_act(jid, state['revision'], A, 'native_activity_end', {})
    old_id = next(key for key, raw in state['actors'][A]['encounter_snapshot']['conditions'].items()
                  if json.loads(raw)['condition_id'] == PRESENCE)
    state = cold().journey_world_fact(jid, state['revision'], {
        'source': REVIEW_SOURCE, 'subject': A, 'kind': REVIEW_KIND, 'scope': old_id,
        'value': {'violated': 0, 'sole_available_way': 0, 'exception': 'none',
            'acts': 'The Warrior ancestor stood guard; the actor now chooses to receive the Healer Office instead.',
            'ruling': 'No recorded Lineage Taboo was violated during the outgoing presence.'},
        'expires_at': 3600, 'readers': []})
    before = dict(state['actors'][A]['resources'])
    state, _ = activity_act(cold, jid, A, option('Healer').candidate_id)
    committed = next(e for e in reversed(state['events']) if e['kind'] == 'NATIVE_ACTIVITY_COMMITTED')
    restored = replay_record(committed)
    actor = restored.actors[A]
    assert actor.resources[RES] == before[RES] - 10
    held = next(c for c in actor.conditions.values() if c.condition_id == PRESENCE)
    assert held.instance_id != old_id and held.data['office'] == 'Healer'
    assert any(c.condition_id == STRAIN for c in actor.conditions.values())
    price = next(e for e in committed['events'] if e['event_type'] == 'PASSIVE_TRIGGERED'
        and e.get('payload', {}).get('checkpoint') == 'ANCESTRAL_WITHDRAWAL')
    assert price['payload']['failed'] == 1 and price['sequence'] < held.applied_sequence
    assert load(cold().journeys.load(jid)).state.model_dump(mode='json') == restored.model_dump(mode='json')


def test_native_threaded_step_preserves_owner_choice_and_is_not_blocked_by_shared_neutral_team(tmp_path, monkeypatch):
    from combat.journey_activity import load, replay_record
    cold, _, _, jid = game(tmp_path, monkeypatch, [SPIKE, THREADED], activity=True)
    state = cold().journey_state(jid)
    relations = {'source':'system:journey.activity', 'subject':A, 'kind':'relations', 'scope':jid,
        'value':{'actors':{min(A,B):{max(A,B):'ENEMY'}}}, 'expires_at':86400, 'readers':[A,B]}
    state = cold().journey_world_fact(jid, state['revision'], relations)
    initial = load(cold().journeys.load(jid))
    assert initial.state.actors[A].team_id == initial.state.actors[B].team_id == 'team:neutral'
    original_position = initial.state.actors[B].position
    offered = next(c for c in initial.legal_candidates() if c.display_name == 'Mind Spike' and c.target_ids == (B,))
    state, prompts = activity_act(cold, jid, A, offered.candidate_id,
        {'choice:needle.soulstring.threaded_resistance':'accept'})
    event = next(event for event in reversed(state['events']) if event['kind'] == 'NATIVE_ACTIVITY_COMMITTED')
    current = replay_record(event)
    assert any(c.data.get('mark_name') == STRING for c in current.actors[B].conditions.values())
    assert current.actors[B].position != original_position
    assert any(p['reaction_source_id'] == 'choice:needle.soulstring.threaded_resistance' and p['reactor_id'] == B for p in prompts)
    assert not any(p['reaction_source_id'] == 'choice:needle.save_choice' for p in prompts)
    assert load(cold().journeys.load(jid)).state.model_dump(mode='json') == current.model_dump(mode='json')


def test_native_measure_uses_actual_hostile_relations_outside_combat_and_spends_after_cold_reload(tmp_path, monkeypatch):
    from combat.journey_activity import load, replay_record
    cold, _, _, jid = game(tmp_path, monkeypatch, [SPIKE, RECEIVE, RECOMPENSE], activity=True)
    state = cold().journey_state(jid)
    cold().journey_world_fact(jid, state['revision'], {'source':'system:journey.activity', 'subject':A,
        'kind':'relations', 'scope':jid, 'value':{'actors':{min(A,B):{max(A,B):'ENEMY'}}},
        'expires_at':86400, 'readers':[A,B]})
    def use(aid, name, target=None, picks=None):
        current = load(cold().journeys.load(jid))
        candidate = next(c for c in current.legal_candidates() if c.display_name == name
                         and (target is None or c.target_ids == (target,)))
        return activity_act(cold, jid, aid, candidate.candidate_id, picks)
    use(A, 'Mind Spike', B)
    use(A, 'End turn')
    state, _ = use(B, 'Mind Spike', A)
    current = load(cold().journeys.load(jid))
    held = [kind for kind, resource in POOL.items() if current.state.actors[A].resources[resource]]
    assert len(held) == 1
    use(B, 'End turn')
    before = load(cold().journeys.load(jid)).state.actors[A].resources[RES]
    state, prompts = use(A, 'Threefold Recompense', B, {'choice:needle.equal_measure.recompense_strike':'spike'})
    event = next(e for e in reversed(state['events']) if e['kind'] == 'NATIVE_ACTIVITY_COMMITTED')
    replayed = replay_record(event)
    assert replayed.actors[A].resources[RES] == before - 5
    assert all(replayed.actors[A].resources[resource] == 0 for resource in POOL.values())
    assert any(p['reaction_source_id'] == 'choice:needle.equal_measure.recompense_strike' for p in prompts)
    assert load(cold().journeys.load(jid)).state.model_dump(mode='json') == replayed.model_dump(mode='json')


def test_unrelated_source_strain_cannot_increase_possession_cost(tmp_path, monkeypatch):
    record = {'covenant':covenant(), 'facts':{
        CHANNELER_SOURCE:{'anchor_strained':entry(0), 'taboo_since_session':entry(0)},
        'another_lineage':{'anchor_strained':entry(1)}}}
    cold, table, mid = game(tmp_path, monkeypatch, [COUNCIL, POSSESSION], owner_record=record)
    turn(table, mid, B)
    before = engine(cold, mid).state.actors[A].resources[RES]
    current, prompts = play(cold, table, mid, 'Mind Spike', A)
    assert current.state.actors[A].resources[RES] == before
    assert not any(p['context']['reaction_source_id'] == 'choice:needle.ancestral.dispute' for p in prompts)


@pytest.mark.parametrize('solo', [False, True])
def test_native_peaceful_activity_keeps_turns_and_transports_private_fact_without_reissuing_it(tmp_path, monkeypatch, solo):
    from combat.fact_consent_admission import combat_records, read as read_fact
    from combat.journey_activity import load, replay_record
    cold, _, _, jid = game(tmp_path, monkeypatch, [WINGS], activity=True, solo=solo,
        owner_record={'facts':{CHANNELER_SOURCE:{'anchor_strained':entry(1)}}})
    before = cold().journey_state(jid)
    receipt = before['fact_consent_admission'][-1]['receipt_id']
    before_clock = before['seconds']
    offered = next(row for row in cold().journey_menu(jid, A)['options']
                   if row['label'] == 'Wingless Ascent')
    state = cold().journey_act(jid, before['revision'], A, offered['kind'], offered['payload'])
    assert not state.get('native_activity_pending')
    event = next(event for event in state['events'] if event['kind'] == 'NATIVE_ACTIVITY_COMMITTED')
    replayed = replay_record(event)
    assert replayed.actors[A].resources[RES] == before['actors'][A]['resources'][RES] - 3
    assert any(c.condition_id == WINGS_OUT for c in replayed.actors[A].conditions.values())
    assert not any(event['event_type'] in ('MATCH_CREATED','INITIATIVE_ROLLED') for event in event['events'])
    assert load(cold().journeys.load(jid)).state.model_dump(mode='json') == replayed.model_dump(mode='json')
    resumed = cold().journey_act(jid, state['revision'], A, 'native_activity_end', {})
    assert resumed['phase'] == 'travel' and resumed['seconds'] == before_clock + 6
    scope = ss.input_scope(CHANNELER_SOURCE, 'anchor_strained')
    record = read_fact(cold().journeys.load(jid), ss.INPUT_SOURCE, A, ss.WORLD_INPUT, scope, A)
    assert record['receipt_id'] == receipt
    assert read_fact(cold().journeys.load(jid), ss.INPUT_SOURCE, A, ss.WORLD_INPUT, scope, B) is None
    current = load(cold().journeys.load(jid))
    assert combat_records(current, current.state.actors[A], source=ss.INPUT_SOURCE)[0]['receipt_id'] == receipt
    if not solo:
        assert not combat_records(current, current.state.actors[B], source=ss.INPUT_SOURCE)
    assert ss.fact(current.state.actors[A], CHANNELER_SOURCE, 'anchor_strained') == 1


@pytest.mark.parametrize('dispute', [0, 1])
def test_possession_covenant_dispute_real_save_on_enemy_turn_cold_replay(tmp_path, monkeypatch, dispute):
    record = {'covenant': covenant(), 'facts': {CHANNELER_SOURCE: {
        'anchor_strained': entry(dispute), 'taboo_since_session': entry(0),
        'faction_dispute': entry('Who owns the Reed burial duty?' if dispute else '')}}}
    cold, table, mid = game(tmp_path, monkeypatch, [COUNCIL, POSSESSION], owner_record=record)
    turn(table, mid, B)
    before = engine(cold, mid).state.actors[A].resources.copy()
    current, prompts = play(cold, table, mid, 'Mind Spike', A)
    owner = current.state.actors[A]
    assert any(p['context']['reactor_id'] == A for p in prompts)
    assert any(c.source_definition_id == POSSESSION and c.condition_id.endswith('reaction_denied') for c in owner.conditions.values())
    assert before[RES] - owner.resources[RES] == (3 if dispute else 0)
    if dispute:
        assert any('dispute' in p['context']['reaction_source_id'] for p in prompts)
    assert ss.read(owner)['covenant'] == covenant()


@pytest.mark.parametrize('strained,taboo,expected', [(0,0,1),(1,0,0),(0,1,0)])
def test_scene_favor_uses_recorded_covenant_eligibility(tmp_path, monkeypatch, strained, taboo, expected):
    record = {'covenant': covenant(), 'facts': {CHANNELER_SOURCE: {
        'anchor_strained': entry(strained), 'taboo_since_session': entry(taboo)}}}
    cold, table, mid = game(tmp_path, monkeypatch, [COUNCIL, POSSESSION], owner_record=record)
    actor = engine(cold, mid).state.actors[A]
    assert actor.resources['resource:named.favor'] == expected


@pytest.mark.parametrize('natural', [15,20])
def test_old_guard_remains_a_player_choice_when_the_attack_still_hits(tmp_path,monkeypatch,natural):
    record = {'covenant':covenant(),'facts':{CHANNELER_SOURCE:{'anchor_strained':entry(0),'taboo_since_session':entry(0)}}}
    cold,table,mid = game(tmp_path,monkeypatch,[COUNCIL,POSSESSION],other=[],kit=AXE,owner_record=record,attack_natural=natural)
    turn(table,mid,B)
    before = engine(cold,mid)
    hit_points = before.state.actors[A].current_hp
    attack = next(c for c in before.legal_candidates() if c.target_ids == (A,)
        and c.source_definition_id in before.action_catalog
        and ((before.action_catalog[c.source_definition_id].parameters.get('typed') or {}).get('weapon') is not None))
    prompts = settle(table,mid,attack.candidate_id,{'choice:needle.ancestral.old_guard':'use'})
    current = engine(cold,mid)
    assert any(p['context']['reaction_source_id'] == 'choice:needle.ancestral.old_guard' for p in prompts)
    assert current.state.actors[A].current_hp < hit_points
    assert current.state.actors[A].resources['resource:named.favor'] == 0
    response = next(e for e in current.events if e.event_type == 'REACTION_RESOLVED' and e.source_definition_id == POSSESSION)
    assert response.payload['hit_after_recheck'] is True


@pytest.mark.parametrize('repeat_identity', [False,True])
def test_lineage_acts_use_actual_event_identity_instead_of_description_text(tmp_path,monkeypatch,repeat_identity):
    record = {'covenant':covenant(),'facts':{CHANNELER_SOURCE:{'anchor_strained':entry(0),'taboo_since_session':entry(0)}}}
    act = {'act_id':'raid:archive:one','kind':'protect','duty':covenant()['duty'],
           'description':'Protect the burial archive','meaningful':1,
           'ruling':'A distinct meaningful raid was resolved; its defenders actually protected the lineage archive.'}
    second = {**act,'act_id':act['act_id'] if repeat_identity else 'raid:archive:two'}
    if repeat_identity:
        with pytest.raises(ValueError,match='only once'):
            game(tmp_path,monkeypatch,[COUNCIL,POSSESSION],owner_record=record,lineage_acts=[act,second])
    else:
        cold,table,mid = game(tmp_path,monkeypatch,[COUNCIL,POSSESSION],owner_record=record,lineage_acts=[act,second])
        assert engine(cold,mid).state.actors[A].resources['resource:named.favor'] == 3


def test_threaded_step_native_failed_spike_uses_forced_path_and_preserves_string(tmp_path, monkeypatch):
    cold, table, mid = game(tmp_path, monkeypatch, [SPIKE, THREADED])
    turn(table, mid, A)
    current, prompts = play(cold, table, mid, 'Mind Spike', B, {'choice:needle.save_choice':'WIS'})
    assert any(p['context']['reaction_source_id'] == 'choice:needle.threaded_step' for p in prompts)
    assert any(p['context']['reaction_source_id'] == 'choice:needle.save_choice' and p['context']['reactor_id'] == B for p in prompts)
    moves = [e for e in current.events if e.event_type == 'MOVEMENT_COMMITTED' and e.actor_id == B]
    assert moves and moves[-1].payload.get('forced') is True
    assert any(STRING.lower().replace(' ', '_') in c.condition_id or c.data.get('mark_name') == STRING
               for c in current.state.actors[B].conditions.values())


def test_counterstep_responds_to_real_willing_movement_once_without_a_reaction(tmp_path,monkeypatch):
    cold,table,mid = game(tmp_path,monkeypatch,[SPIKE,THREADED])
    turn(table,mid,A)
    play(cold,table,mid,'Mind Spike',B)
    turn(table,mid,B)
    before = engine(cold,mid)
    reaction = before.state.actors[A].reaction_available
    sequence = before.state.event_sequence
    def walk():
        current = cold()._load_session(mid).engine
        candidate = next(c for c in current.legal_candidates() if c.kind == 'MOVE' and c.destination
            and current.grid.distance_ft(current.state.actors[A].position,c.destination) <= 25)
        return settle(table,mid,candidate.candidate_id)
    prompts = walk()
    current = engine(cold,mid)
    assert any('counterstep' in p['context']['reaction_source_id'].lower() for p in prompts)
    own_moves = [e for e in current.events if e.sequence > sequence and e.event_type == 'MOVEMENT_COMMITTED' and e.actor_id == A]
    assert len(own_moves) == 1 and not own_moves[0].payload.get('forced')
    assert current.state.actors[A].reaction_available == reaction
    sequence = current.state.event_sequence
    walk()
    assert not [e for e in engine(cold,mid).events if e.sequence > sequence and e.event_type == 'MOVEMENT_COMMITTED' and e.actor_id == A]


def test_threaded_step_keeps_vertical_direction_and_native_falling_reachable(tmp_path,monkeypatch):
    cold,table,mid = game(tmp_path,monkeypatch,[SPIKE,THREADED])
    turn(table,mid,A)
    current,prompts = play(cold,table,mid,'Mind Spike',B,
        {'choice:needle.threaded_step':'cell:4,6,1'})
    moves = [e for e in current.events if e.event_type == 'MOVEMENT_COMMITTED' and e.actor_id == B]
    assert any(e.payload.get('forced') is True and e.payload['destination']['z'] == 1 for e in moves)
    assert sum(e.payload.get('fall_distance_ft',0) for e in moves) == 5
    assert current.state.actors[B].position.z == 0
    assert any(c.data.get('mark_name') == STRING for c in current.state.actors[B].conditions.values())


@pytest.mark.parametrize('mode,condition', [('ascending', BEAT), ('glide', GLIDE), ('pinions', PINIONS)])
def test_wingless_turn_start_modes_committed_and_replayed(tmp_path, monkeypatch, mode, condition):
    cold, table, mid = game(tmp_path, monkeypatch, [WINGS])
    turn(table, mid, A)
    play(cold, table, mid, 'Wingless Ascent')
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    turn(table, mid, A, {'choice:needle.seraphic.wingless_mode': mode})
    actor = engine(cold, mid).state.actors[A]
    assert any(c.condition_id == condition for c in actor.conditions.values())
    if mode == 'ascending':
        assert next(c for c in actor.conditions.values() if c.condition_id == WINGS_OUT).data['ascending_turns'] == 1


@pytest.mark.parametrize('reactivate', [False, True])
def test_fourth_ascending_beat_costs_one_extra_resonance(tmp_path, monkeypatch, reactivate):
    cold, table, mid = game(tmp_path, monkeypatch, [WINGS])
    turn(table, mid, A)
    play(cold, table, mid, 'Wingless Ascent')
    for count in range(1,5):
        settle(table, mid, table.state(mid)['menu']['end_turn'])
        turn(table, mid, A, {'choice:needle.seraphic.wingless_mode': 'ascending'})
        actor = engine(cold, mid).state.actors[A]
        assert next(c for c in actor.conditions.values() if c.condition_id == WINGS_OUT).data['ascending_turns'] == count
        assert actor.resources[RES] == 27 - int(count > 3) - 3 * int(reactivate and count > 3)
        if reactivate and count == 3:
            play(cold, table, mid, 'Wingless Ascent')


def test_ascending_beat_tracks_real_walking_speed_changes_after_mode_selection(tmp_path, monkeypatch):
    from combat.flight import profile
    from combat.ext.source_penalties import SOURCE, KIND
    cold, table, mid = game(tmp_path, monkeypatch, [WINGS])
    turn(table, mid, A)
    play(cold, table, mid, 'Wingless Ascent')
    turn(table, mid, B)
    turn(table, mid, A, {'choice:needle.seraphic.wingless_mode':'ascending'})
    before = engine(cold, mid)
    assert profile(before, before.state.actors[A]).speed_ft == before._effective_speed(before.state.actors[A]) == 30
    now = (before.state.round_number - 1) * 6
    cold().declare_combat_world_fact(mid, state_version=before.state.state_version,
        payload={'source':SOURCE, 'subject':A, 'kind':KIND, 'scope':'march-fatigue',
            'value':{'penalty_id':'march-fatigue', 'cause':'forced_march', 'label':'Forced march fatigue',
                     'source_rule':'Recorded campaign rule: nonmagical march fatigue reduces Speed by 10 feet.',
                     'ruling':'The real penalty has not become Exhaustion.', 'speed_reduction_ft':10},
            'expires_at':now + 60, 'readers':[A]})
    current = engine(cold, mid)
    assert profile(current, current.state.actors[A]).speed_ft == current._effective_speed(current.state.actors[A]) == 20


@pytest.mark.parametrize('destination',[(3,6,4),(8,5,4)])
def test_folding_glide_uses_native_unsupported_movement_with_twenty_foot_limit_and_safe_landing(tmp_path,monkeypatch,destination):
    cold,table,mid = game(tmp_path,monkeypatch,[WINGS])
    turn(table,mid,A)
    play(cold,table,mid,'Wingless Ascent')
    turn(table,mid,B)
    turn(table,mid,A,{'choice:needle.seraphic.wingless_mode':'glide'})
    current = engine(cold,mid)
    candidates = [c for c in current.legal_candidates() if c.kind == 'MOVE' and c.destination]
    assert not any((c.destination.x,c.destination.y,c.destination.z) == (3,6,5) for c in candidates)
    chosen = next(c for c in candidates if (c.destination.x,c.destination.y,c.destination.z) == destination)
    if destination[0] != 3:
        # The direct early-rise approach exceeds the gap. A later-rise path
        # reaches the same endpoint legally; preserve that native option.
        assert any(p.z == 0 and p != chosen.canonical_path[0] for p in chosen.canonical_path)
    hit_points = current.state.actors[A].current_hp
    sequence = current.state.event_sequence
    settle(table,mid,chosen.candidate_id)
    current = engine(cold,mid)
    moves = [e for e in current.events if e.sequence > sequence and e.event_type == 'MOVEMENT_COMMITTED' and e.actor_id == A]
    assert max(p['z'] for e in moves for p in e.payload.get('path',[])) == 4
    assert current.state.actors[A].position.z == 0 and current.state.actors[A].current_hp == hit_points
    assert not any(e.payload.get('fall_distance_ft') for e in moves)
    turn(table,mid,B)
    turn(table,mid,A,{'choice:needle.seraphic.wingless_mode':'pinions'})
    assert not any(c.condition_id == GLIDE for c in engine(cold,mid).state.actors[A].conditions.values())


@pytest.mark.parametrize('kind', ['liquid', 'fragile'])
def test_folding_glide_crosses_real_recorded_surfaces_beyond_the_air_gap_limit(tmp_path, monkeypatch, kind):
    surfaces = [{'id':'high-crossing', 'label':'Suspended water surface' if kind == 'liquid' else 'Fragile silk surface',
                 'kind':kind, 'cells':[[x,6,5] for x in range(3,8)]}]
    cold, table, mid = game(tmp_path, monkeypatch, [WINGS], surfaces=surfaces,
        positions={A:{'x':2,'y':6,'z':5},B:{'x':10,'y':10}}, columns=[(2,6,25),(8,6,25)])
    turn(table, mid, A)
    before = engine(cold, mid)
    assert before.battlefield_document['map_surfaces'] == surfaces
    from combat.tabletop import battlefield_as_map
    assert battlefield_as_map(before.battlefield_document)['surfaces'] == surfaces
    from combat.map_surfaces import covers
    from combat.gate2_runtime_models import Position
    assert covers(before, before.state.actors[A], Position(x=4,y=6,z=5))
    assert not covers(before, before.state.actors[A], Position(x=4,y=6,z=6))
    assert not any(c.kind == 'MOVE' and c.destination and (c.destination.x,c.destination.y,c.destination.z) == (8,6,5)
                   for c in before.legal_candidates())
    play(cold, table, mid, 'Wingless Ascent')
    turn(table, mid, B)
    turn(table, mid, A, {'choice:needle.seraphic.wingless_mode':'glide'})
    current = engine(cold, mid)
    target = next(c for c in current.legal_candidates() if c.kind == 'MOVE' and c.destination
                  and (c.destination.x,c.destination.y,c.destination.z) == (8,6,5))
    assert all(point.z == 5 for point in target.canonical_path)
    hp = current.state.actors[A].current_hp
    settle(table, mid, target.candidate_id)
    current = engine(cold, mid)
    assert (current.state.actors[A].position.x,current.state.actors[A].position.y,current.state.actors[A].position.z) == (8,6,5)
    assert current.state.actors[A].current_hp == hp


@pytest.mark.parametrize('next_mode', ['glide', 'pinions'])
def test_folding_liquid_surface_renewal_or_safe_descent_is_owned_at_turn_start(tmp_path, monkeypatch, next_mode):
    surfaces = [{'id':'water-surface', 'label':'Suspended water surface', 'kind':'liquid',
                 'cells':[[x,6,5] for x in range(3,8)]}]
    cold, table, mid = game(tmp_path, monkeypatch, [WINGS], surfaces=surfaces,
        positions={A:{'x':2,'y':6,'z':5},B:{'x':10,'y':10}}, columns=[(2,6,25)])
    turn(table, mid, A)
    play(cold, table, mid, 'Wingless Ascent')
    turn(table, mid, B)
    turn(table, mid, A, {'choice:needle.seraphic.wingless_mode':'glide'})
    current = engine(cold, mid)
    target = next(c for c in current.legal_candidates() if c.kind == 'MOVE' and c.destination
                  and (c.destination.x,c.destination.y,c.destination.z) == (7,6,5))
    settle(table, mid, target.candidate_id)
    current = engine(cold, mid)
    hp = current.state.actors[A].current_hp
    turn(table, mid, B)
    turn(table, mid, A, {'choice:needle.seraphic.wingless_mode':next_mode})
    current = engine(cold, mid)
    assert current.state.actors[A].current_hp == hp
    assert current.state.actors[A].position.z == (5 if next_mode == 'glide' else 0)


@pytest.mark.parametrize('bad_cell', [[3,6,5.0], [12,6,5], [3,6,-1]])
def test_map_surface_producer_rejects_inexact_or_out_of_bounds_geometry(bad_cell):
    with pytest.raises(ValueError):
        normalize_map({'display_name':'Invalid surface', 'width_squares':12, 'height_squares':12,
            'surfaces':[{'id':'surface', 'label':'Water surface', 'kind':'liquid', 'cells':[bad_cell]}]})


def test_deny_passage_host_expulsion_uses_recorded_host_and_native_crossing(tmp_path, monkeypatch):
    cold, table, mid = game(tmp_path, monkeypatch, [DENY],
        other_record={'facts': {B: {'host_id': {**entry(A), 'visibility': 'public'},
            'presence_kind': {**entry('occupying_spirit'), 'visibility': 'public'}}}})
    turn(table, mid, B)
    current = cold()._load_session(mid).engine
    candidate = next(c for c in current.legal_candidates() if c.kind == 'MOVE' and c.destination
                     and (c.destination.x, c.destination.y) == (4,5))
    prompts = settle(table, mid, candidate.candidate_id, {'choice:needle.boundary.deny': 'deny',
        'choice:needle.boundary.deny_outcome': 'expel'})
    current = engine(cold, mid)
    assert any(p['context']['reaction_source_id'] == 'choice:needle.boundary.expel_space' for p in prompts)
    assert ss.fact(current.state.actors[B], B, 'host_id') is None
    assert current.state.actors[A].resources[RES] == 26


def test_deny_passage_does_not_reveal_a_private_host_record(tmp_path, monkeypatch):
    cold, table, mid = game(tmp_path, monkeypatch, [DENY], other_record={'facts': {B: {
        'host_id': entry(A), 'presence_kind': entry('possessing_spirit')}}})
    turn(table, mid, B)
    current = cold()._load_session(mid).engine
    candidate = next(c for c in current.legal_candidates() if c.kind == 'MOVE' and c.destination
                     and (c.destination.x,c.destination.y) == (4,5))
    prompts = settle(table, mid, candidate.candidate_id)
    choice = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.boundary.deny_outcome')
    assert {o['id'] for o in choice['choice']['options']} == {'stop','return'}
    assert ss.fact(engine(cold, mid).state.actors[B], B, 'host_id') == A


@pytest.mark.parametrize('facts,message', [
    ({'host_id': entry(A)}, 'actual possessing or occupying spirit'),
    ({'host_id': entry(B), 'presence_kind': entry('occupying_spirit')}, 'its own host'),
    ({'host_id': entry(A), 'presence_kind': entry('passenger')}, 'possessing spirit or an occupying spirit'),
])
def test_host_declaration_rejects_untyped_passenger_and_self_relations(tmp_path, monkeypatch, facts, message):
    with pytest.raises((ValueError, RuntimeError), match=message):
        game(tmp_path, monkeypatch, [DENY], other_record={'facts': {B: facts}})


def test_native_admission_authority_private_amendment_and_expiry_cold_replay(tmp_path, monkeypatch):
    cold, table, mid = game(tmp_path, monkeypatch, [COUNCIL, POSSESSION],
        owner_record={'covenant': covenant(), 'facts': {CHANNELER_SOURCE: {
            'anchor_strained': entry(0), 'taboo_since_session': entry(0)}}})
    payload = {'source': ss.INPUT_SOURCE, 'subject': B, 'kind': ss.SUBJECT_INPUT,
        'scope': ss.input_scope(A, 'willing'), 'value': {'facts': {A: {'willing': entry(1)}}},
        'expires_at': 6, 'readers': [A]}
    version = engine(cold, mid).state.state_version
    with pytest.raises(ValueError, match='cannot supply|cannot provide'):
        cold().declare_combat_world_fact(mid, state_version=version, payload=payload)
    assert engine(cold, mid).state.state_version == version
    with pytest.raises(ValueError, match='own source-scoped facts'):
        cold().declare_combat_actor_fact(mid, A, state_version=version, payload=payload)
    cold().declare_combat_actor_fact(mid, B, state_version=version, payload=payload)
    current = engine(cold, mid)
    assert ss.willing(current.state.actors[A], current.state.actors[B])
    assert ss.visible_fact(current, current.state.actors[A], current.state.actors[B], A, 'willing') == 1
    cold().declare_combat_actor_fact(mid, B, state_version=current.state.state_version,
        payload={**payload, 'value': {'facts': {A: {'willing': entry(0)}}}, 'readers': []})
    current = engine(cold, mid)
    assert ss.fact(current.state.actors[B], A, 'willing') == 0
    assert ss.visible_fact(current, current.state.actors[A], current.state.actors[B], A, 'willing') is None
    world = {'source': ss.INPUT_SOURCE, 'subject': A, 'kind': ss.WORLD_INPUT,
        'scope': ss.input_scope(CHANNELER_SOURCE, 'anchor_strained'),
        'value': {'facts': {CHANNELER_SOURCE: {'anchor_strained': entry(1)}}},
        'expires_at': 6, 'readers': []}
    with pytest.raises(ValueError, match='table-owner input'):
        cold().declare_combat_actor_fact(mid, A, state_version=current.state.state_version, payload=world)
    cold().declare_combat_world_fact(mid, state_version=current.state.state_version, payload=world)
    assert ss.fact(engine(cold, mid).state.actors[A], CHANNELER_SOURCE, 'anchor_strained') == 1
    for _ in range(4):
        if engine(cold, mid).state.round_number >= 2:
            break
        settle(table, mid, table.state(mid)['menu']['end_turn'])
    current = engine(cold, mid)
    assert current.state.round_number >= 2
    assert ss.fact(current.state.actors[B], A, 'willing') is None
    # The expired amendment cannot revive an older still-live declaration.
    assert ss.fact(current.state.actors[A], CHANNELER_SOURCE, 'anchor_strained') is None


@pytest.mark.parametrize('route_wins', [False,True])
def test_equal_route_authority_rolls_both_controllers_and_ties_stop_crossing(tmp_path,monkeypatch,route_wins):
    step = 'tianxia.tradition.spirit.boundary_walker.feature.threshold_step'
    cold,table,mid = game(tmp_path,monkeypatch,[DENY],other=[step],
        check_results={A:1,B:20 if route_wins else 1})
    turn(table,mid,B)
    origin = engine(cold,mid).state.actors[B].position
    current,prompts = play(cold,table,mid,'Threshold Step')
    contests = [e for e in current.events if e.event_type == 'CHECK_ROLLED' and e.payload.get('boundary_collision') == 1]
    assert len(contests) == 1 and contests[0].payload['success'] is route_wins
    assert (current.state.actors[B].position != origin) is route_wins
    assert current.state.actors[A].resources[RES] == 26


def test_successful_native_passage_save_commits_and_expires_the_incorporeal_attempt_lock(tmp_path, monkeypatch):
    """Native delivery/expiry plus a pure state-attempt contract guard.

    The probe does not claim an unimplemented incorporeal ability was acquired.
    """
    from combat import ext
    from combat.ext import spirit_traditions as traditions
    step = 'tianxia.tradition.spirit.boundary_walker.feature.threshold_step'
    cold, table, mid = game(tmp_path, monkeypatch, [DENY], other=[step], save_results={B:20})
    turn(table, mid, B)
    current, _ = play(cold, table, mid, 'Threshold Step')
    mover = current.state.actors[B]
    assert any(c.condition_id == 'condition:typed.boundary_crossing_lock' for c in mover.conditions.values())
    assert current._effective_speed(mover) == 20
    context = traditions.context(current, mover, traditions.feature_action(current, mover, step), [mover])
    assert False in ext.run_strict('condition_attempt', context, mover, {'condition':'incorporeal'})
    assert False not in ext.run_strict('condition_attempt', context, mover, {'condition':'invisible'})
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    current = engine(cold, mid)
    mover = current.state.actors[B]
    assert not any(c.condition_id == 'condition:typed.boundary_crossing_lock' for c in mover.conditions.values())
    context = traditions.context(current, mover, traditions.feature_action(current, mover, step), [mover])
    assert False not in ext.run_strict('condition_attempt', context, mover, {'condition':'incorporeal'})


def test_deny_passage_uses_the_actual_displacement_source_instead_of_the_passengers_cl(tmp_path, monkeypatch):
    """Existing Spatial Displacement is only the native trigger, not a Talent audit."""
    source = 'tianxia.talent.space.spatial_displacement'
    cold, table, mid = game(tmp_path, monkeypatch, [DENY], other=[source], other_cl=15,
        positions={A:{'x':4,'y':6},B:{'x':3,'y':6}})
    turn(table, mid, B)
    before = engine(cold, mid).state.actors[A].resources[RES]
    current, prompts = play(cold, table, mid, 'Spatial Displacement', A,
        {'choice:needle.subject_destination':'cell:4,5'})
    knowledge = [entry for key, entry in ss.read(current.state.actors[A]).get('facts', {}).get(DENY, {}).items()
                 if key.startswith('route_knowledge:')]
    assert len(knowledge) == 1 and knowledge[0]['source_cl'] == 15
    assert current.state.actors[A].resources[RES] == before - 4
    assert any(p['context']['reaction_source_id'] == 'choice:needle.boundary.route_knowledge' for p in prompts)
    assert not ss.read(current.state.actors[B]).get('facts', {}).get(DENY)


def test_stronger_native_route_information_persists_for_only_the_reacting_owner(tmp_path,monkeypatch):
    step = 'tianxia.tradition.spirit.boundary_walker.feature.threshold_step'
    cold,table,mid = game(tmp_path,monkeypatch,[DENY],other=[step],other_cl=15)
    turn(table,mid,B)
    current,prompts = play(cold,table,mid,'Threshold Step')
    facts = ss.read(current.state.actors[A])['facts'][DENY]
    key = next(k for k in facts if k.startswith('route_knowledge:'))
    learned = json.loads(facts[key]['value'])
    assert learned['source_direction'] and learned['anchor_exists'] == 0
    assert learned['destination_class'] == 'a visible space on the same battlefield'
    assert ss.visible_fact(current,current.state.actors[B],current.state.actors[A],DENY,key) is None
    assert any(p['context']['reaction_source_id'] == 'choice:needle.boundary.route_knowledge' for p in prompts)


def test_a_fact_declaration_cannot_upgrade_the_authority_of_an_acquired_technique(tmp_path,monkeypatch):
    step = 'tianxia.tradition.spirit.boundary_walker.feature.threshold_step'
    with pytest.raises(ValueError,match='source power'):
        game(tmp_path,monkeypatch,[DENY],other=[step],
             other_record={'facts':{step:{'route_category':entry('world_route')}}})


def test_recompense_measures_come_from_completed_hostile_intent_and_are_spent_after_reload(tmp_path, monkeypatch):
    cold, table, mid = game(tmp_path, monkeypatch, [SPIKE, RECEIVE, RECOMPENSE])
    turn(table, mid, B)
    current, _ = play(cold, table, mid, 'Mind Spike', A)
    actor = current.state.actors[A]
    assert sum(actor.resources.get(v,0) for v in POOL.values()) == 1
    kind = next(k for k,v in POOL.items() if actor.resources.get(v))
    assert ss.fact(actor, RECEIVE, 'measure:' + kind)
    turn(table, mid, A)
    play(cold, table, mid, 'Mind Spike', B)
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    turn(table, mid, A)
    current, _ = play(cold, table, mid, 'Threefold Recompense', B,
        {'choice:needle.equal_measure.recompense_strike': 'spike'})
    assert current.state.actors[A].resources[POOL[kind]] == 0
    assert any(e.event_type == 'DAMAGE_ROLLED' and len(e.payload.get('dice', [])) == 3 for e in current.events)


def test_recompense_successful_mind_spike_save_halves_both_packets_and_spends_measure(tmp_path,monkeypatch):
    cold,table,mid = game(tmp_path,monkeypatch,[SPIKE,RECEIVE,RECOMPENSE],dc=10,save_results={B:[1,20]})
    turn(table,mid,B)
    play(cold,table,mid,'Mind Spike',A)
    turn(table,mid,A)
    play(cold,table,mid,'Mind Spike',B)
    turn(table,mid,B)
    turn(table,mid,A)
    sequence = engine(cold,mid).state.event_sequence
    current,_ = play(cold,table,mid,'Threefold Recompense',B,{'choice:needle.equal_measure.recompense_strike':'spike'})
    events = [e for e in current.events if e.sequence > sequence]
    assert any(e.event_type == 'SAVE_ROLLED' and e.actor_id == B and e.payload.get('success') is True for e in events)
    rolls = [e for e in events if e.event_type == 'DAMAGE_ROLLED' and e.actor_id == A and B in e.target_ids]
    damage = [e for e in events if e.event_type == 'DAMAGE_COMMITTED' and B in e.target_ids]
    assert len(rolls) == len(damage) == 2
    assert [e.payload['hp_damage'] for e in damage] == [e.payload['total']//2 for e in rolls]
    assert current.state.actors[A].resources[POOL['impact']] == 0
    assert not any(e.event_type == 'CONDITION_APPLIED' and e.actor_id == A and B in e.target_ids for e in events)


def test_recompense_real_weapon_miss_spends_its_measure_without_added_damage_or_riders(tmp_path,monkeypatch):
    cold,table,mid = game(tmp_path,monkeypatch,[SPIKE,RECEIVE,RECOMPENSE],kit=AXE,attack_natural=1)
    turn(table,mid,B)
    play(cold,table,mid,'Mind Spike',A)
    turn(table,mid,A)
    play(cold,table,mid,'Mind Spike',B)
    turn(table,mid,B)
    turn(table,mid,A)
    current = engine(cold,mid)
    attack = next(c for c in current.legal_candidates() if c.target_ids == (B,)
        and c.source_definition_id in current.action_catalog
        and ((current.action_catalog[c.source_definition_id].parameters.get('typed') or {}).get('weapon') is not None))
    sequence = current.state.event_sequence
    current,_ = play(cold,table,mid,'Threefold Recompense',B,
        {'choice:needle.equal_measure.recompense_strike':attack.source_definition_id})
    events = [e for e in current.events if e.sequence > sequence]
    assert any(e.event_type == 'ATTACK_ROLLED' and e.actor_id == A and e.payload.get('natural_result') == 1 for e in events)
    assert not any(e.event_type == 'DAMAGE_COMMITTED' and B in e.target_ids for e in events)
    assert current.state.actors[A].resources[POOL['impact']] == 0


def test_spiritual_contract_rejects_incomplete_covenant_and_float_facts():
    with pytest.raises(ValueError):
        ss.validate({'covenant': {'membership': 'invented'}})
    with pytest.raises(ValueError):
        ss.validate({'facts': {'source': {'anchor_strained': entry(0.5)}}})


def test_wrong_owner_cannot_acquire_covenant_through_a_fact_record(tmp_path, monkeypatch):
    with pytest.raises(ValueError, match='Ancestral Channeler'):
        game(tmp_path, monkeypatch, [], owner_record={'covenant': covenant()})


def test_unowned_characters_have_no_spiritual_receipt_or_mode_choices(tmp_path, monkeypatch):
    cold, table, mid = game(tmp_path, monkeypatch, [], other=())
    current = engine(cold, mid)
    assert not ss.read(current.state.actors[A]) and not ss.read(current.state.actors[B])
    assert not any('Wingless' in c.display_name or 'Possession by' in c.display_name
                   for c in current.legal_candidates())


def test_threaded_step_excludes_a_recorded_obviously_lethal_destination(tmp_path, monkeypatch):
    record = {'facts': {'cell:3,5': {'obviously_lethal': entry(1)}}}
    cold, table, mid = game(tmp_path, monkeypatch, [SPIKE, THREADED], owner_record=record)
    turn(table, mid, A)
    current, prompts = play(cold, table, mid, 'Mind Spike', B)
    destinations = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.threaded_step')
    assert 'cell:3,5' not in [o['id'] for o in destinations['choice']['options']]


def test_threaded_step_cannot_move_a_huge_target(tmp_path, monkeypatch):
    cold, table, mid = game(tmp_path, monkeypatch, [SPIKE, THREADED], size='Huge')
    turn(table, mid, A)
    current, prompts = play(cold, table, mid, 'Mind Spike', B)
    assert current.state.actors[B].size_category == 'Huge'
    assert not any(p['context']['reaction_source_id'] == 'choice:needle.threaded_step' for p in prompts)


def test_inherited_method_defends_actual_athletics_contest_on_enemy_turn(tmp_path, monkeypatch):
    record = {'covenant': covenant(), 'facts': {CHANNELER_SOURCE: {
        'anchor_strained': entry(0), 'taboo_since_session': entry(0)}}}
    cold, table, mid = game(tmp_path, monkeypatch, [COUNCIL, POSSESSION],
        other=['TAL_DARK_TENEBROUS_LEGERDEMAIN'], owner_record=record, kit=AXE,
        check_results={A: 1, B: 20})
    turn(table, mid, B)
    play(cold, table, mid, 'Shape Darkness: Tenebrous Legerdemain')
    play(cold, table, mid, 'Darkness', at=(3,6,0))
    current = engine(cold, mid)
    if not any(c.display_name == 'Tenebrous Legerdemain: pull a weapon away' for c in current.legal_candidates()):
        settle(table, mid, table.state(mid)['menu']['end_turn'])
        turn(table, mid, B)
    current, prompts = play(cold, table, mid, 'Tenebrous Legerdemain: pull a weapon away', A)
    assert any(e.event_type == 'D20_REWRITTEN' and e.source_definition_id == POSSESSION for e in current.events)
    assert any(p['context']['reactor_id'] == A and 'Possession by the Past' in str(p) for p in prompts)


@pytest.mark.parametrize('associated', [True, False])
def test_inherited_method_actual_brute_check_uses_recorded_office_only(tmp_path, monkeypatch, associated):
    duties = covenant()
    if not associated:
        duties['offices'] = ['Healer', 'Wayfarer','Archivist']
    record = {'covenant': duties, 'facts': {CHANNELER_SOURCE: {
        'anchor_strained': entry(0), 'taboo_since_session': entry(0)}}}
    cold, table, mid = game(tmp_path, monkeypatch, [COUNCIL, POSSESSION, 'BRUTE_BASE_BRUTAL_SHOVE'],
        other=[], owner_record=record, check_results={A: 1, B: 20})
    turn(table, mid, A)
    current, prompts = play(cold, table, mid, 'Brutal Shove', B)
    rewritten = [e for e in current.events if e.event_type == 'D20_REWRITTEN' and e.source_definition_id == POSSESSION]
    assert bool(rewritten) is associated
    assert current.state.actors[A].resources['resource:named.favor'] == int(not associated)


def test_player_owns_possession_and_payment_choices_during_real_local_ai_turn(tmp_path, monkeypatch):
    record = {'covenant': covenant(), 'facts': {CHANNELER_SOURCE: {
        'anchor_strained': entry(0), 'taboo_since_session': entry(0)}}}
    cold, table, mid = game(tmp_path, monkeypatch, [COUNCIL, POSSESSION], owner_record=record,
                           modes={A:'MANUAL',B:'LOCAL_AUTO'})
    turn(table, mid, B)
    prompts = []
    for _ in range(4):
        if table.state(mid)['menu']['actor_id'] != B:
            break
        prompts += settle(table, mid, 'automatic', {POSSESSION:'first',
            'choice:needle.ancestral.possession_payment':'resonance'}, auto=True)
        if any(p['context']['reactor_id'] == A for p in prompts):
            break
    current = engine(cold, mid)
    assert prompts and all(p['context']['reactor_id'] == A for p in prompts)
    assert any('Mind Spike' in str(p) and 'Possession by the Past' in str(p) for p in prompts)
    assert current.state.actors[A].resources['resource:named.favor'] == 1
    assert current.state.actors[A].resources[RES] == 28


@pytest.mark.parametrize('new_scene',[False,True])
def test_scene_clock_only_refills_favor_at_a_real_declared_scene_boundary(tmp_path, monkeypatch,new_scene):
    record = {'covenant': covenant(), 'facts': {CHANNELER_SOURCE: {
        'anchor_strained': entry(0), 'taboo_since_session': entry(0)}}}
    cold, table, mid, jid = game(tmp_path, monkeypatch, [COUNCIL, POSSESSION], owner_record=record,
        maximum_rounds=1, return_journey=True)
    turn(table, mid, B)
    play(cold, table, mid, 'Mind Spike', A)
    for _ in range(4):
        if engine(cold, mid).state.terminal_result:
            break
        settle(table, mid, table.state(mid)['menu']['end_turn'])
    assert engine(cold, mid).state.actors[A].resources['resource:named.favor'] == 0
    state = cold().journey_resume(jid, cold().journey_state(jid)['revision'])
    if new_scene:
        state = cold().journey_end_scene(jid,state['revision'],
            'The siege ended; the group entered the separately bounded burial-archive scene.')
        assert cold().journey_state(jid)['actors'][A]['resources']['resource:named.favor'] == 0
    next_mid = cold().journey_start_combat(jid, state['revision'], {A:'team:a',B:'team:b'})['match_id']
    assert engine(cold, next_mid).state.actors[A].resources['resource:named.favor'] == int(new_scene)


@pytest.mark.parametrize('new_scene',[False,True])
@pytest.mark.parametrize('feature',[WINGS,THREADED])
def test_spiritual_effects_follow_the_source_owners_scene_after_native_return(tmp_path,monkeypatch,new_scene,feature):
    cold,table,mid,jid = game(tmp_path,monkeypatch,[SPIKE,feature],other=[],maximum_rounds=1,return_journey=True)
    turn(table,mid,A)
    play(cold,table,mid,'Wingless Ascent' if feature == WINGS else 'Mind Spike',None if feature == WINGS else B)
    for _ in range(4):
        if engine(cold,mid).state.terminal_result:
            break
        settle(table,mid,table.state(mid)['menu']['end_turn'])
    state = cold().journey_resume(jid,cold().journey_state(jid)['revision'])
    if new_scene:
        # A real table-owner boundary ends the source's scene; the subject's
        # clock must not keep somebody else's String alive by accident.
        state = cold().journey_end_scene(jid,state['revision'],
            'The previous bounded spiritual scene ended before this new crossing.')
    next_mid = cold().journey_start_combat(jid,state['revision'],{A:'team:a',B:'team:b'})['match_id']
    current = engine(cold,next_mid)
    if feature == WINGS:
        assert any(c.condition_id == WINGS_OUT for c in current.state.actors[A].conditions.values()) is (not new_scene)
    else:
        assert any(c.data.get('mark_name') == STRING for c in current.state.actors[B].conditions.values()) is (not new_scene)


@pytest.mark.parametrize('mode', ['step', 'push'])
def test_motion_recompense_comes_from_real_hostile_shove_and_orders_movement(tmp_path, monkeypatch, mode):
    cold, table, mid = game(tmp_path, monkeypatch, [SPIKE, RECEIVE, RECOMPENSE], other=[], check_results={A:1,B:20})
    turn(table, mid, A)
    play(cold, table, mid, 'Mind Spike', B)
    turn(table, mid, B)
    play(cold, table, mid, 'Shove: Prone', A)
    current = engine(cold, mid)
    assert current.state.actors[A].resources[POOL['motion']] == 1
    turn(table, mid, A)
    before = current.state.event_sequence
    current, prompts = play(cold, table, mid, 'Threefold Recompense', B,
        {'choice:needle.equal_measure.recompense_strike': 'spike',
         'choice:needle.equal_measure.recompense_motion': mode})
    new = [e for e in current.events if e.sequence > before]
    movement = next(e for e in new if e.event_type == 'MOVEMENT_COMMITTED' and e.actor_id == (A if mode == 'step' else B))
    damage = next(e for e in new if e.event_type == 'DAMAGE_COMMITTED')
    assert (movement.sequence < damage.sequence) is (mode == 'step')
    assert current.state.actors[A].resources[POOL['motion']] == 0


@pytest.mark.parametrize('cells', [1,3])
def test_motion_measure_records_only_actual_ten_foot_denial_on_a_legal_route(tmp_path, monkeypatch, cells):
    cold, table, mid = game(tmp_path,monkeypatch,[RECEIVE],other=[DENY],
        positions={A:{'x':4,'y':6},B:{'x':3,'y':6}})
    turn(table,mid,A)
    current = cold()._load_session(mid).engine
    candidate = next(c for c in current.legal_candidates() if c.kind == 'MOVE' and c.destination
        and (c.destination.x,c.destination.y,c.destination.z) == (4,6-cells,0)
        and all(p.x == 4 for p in c.canonical_path))
    settle(table,mid,candidate.candidate_id,{'choice:needle.equal_measure.receive':'motion' if cells >= 2 else 'intent'})
    current = engine(cold,mid)
    from combat.movement_steps import is_denial_event
    receipts = [e for e in current.events if is_denial_event(e)]
    assert len(receipts) == 1 and receipts[0].actor_id == B and receipts[0].target_ids == (A,)
    assert receipts[0].payload['denied_ft'] == 5*cells
    assert current.state.actors[A].resources[POOL['motion']] == int(cells >= 2)


def test_intent_recompense_two_different_pressure_effects_and_source_expiry(tmp_path, monkeypatch):
    cold, table, mid = game(tmp_path, monkeypatch, [SPIKE, RECEIVE, RECOMPENSE])
    turn(table, mid, B)
    play(cold, table, mid, 'Mind Spike', A, {'choice:needle.equal_measure.receive': 'intent'})
    turn(table, mid, A)
    play(cold, table, mid, 'Mind Spike', B)
    turn(table, mid, B)
    turn(table, mid, A)
    current, _ = play(cold, table, mid, 'Threefold Recompense', B,
        {'choice:needle.equal_measure.recompense_strike': 'spike'})
    pressure = [c for c in current.state.actors[B].conditions.values() if 'spirit_awakening_pressure.' in c.condition_id
                and c.source_actor_id == A]
    assert len({c.condition_id for c in pressure}) == 2
    assert current.state.actors[A].resources[POOL['intent']] == 0


@pytest.mark.parametrize('feet', [30,90])
def test_ascending_beat_commits_safe_descent_then_only_remaining_actual_fall(tmp_path, monkeypatch, feet):
    cold, table, mid = game(tmp_path, monkeypatch, [WINGS], speed=feet)
    turn(table, mid, A)
    play(cold, table, mid, 'Wingless Ascent')
    turn(table, mid, B)
    turn(table, mid, A, {'choice:needle.seraphic.wingless_mode': 'ascending'})
    current = cold()._load_session(mid).engine
    candidate = next(c for c in current.legal_candidates() if c.kind == 'MOVE' and c.destination
                     and (c.destination.x,c.destination.y,c.destination.z) == (3,6,feet//5))
    settle(table, mid, candidate.candidate_id)
    before = engine(cold, mid).state.actors[A].current_hp
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    current = engine(cold, mid)
    assert current.state.actors[A].position.z == 0
    falls = [e for e in current.events if e.event_type == 'MOVEMENT_COMMITTED' and e.actor_id == A
             and e.payload.get('fall_distance_ft')]
    assert sum(e.payload['fall_distance_ft'] for e in falls) == max(0, feet-60)
    assert (current.state.actors[A].current_hp < before) is (feet > 60)


@pytest.mark.parametrize('feet', [30,60])
@pytest.mark.parametrize('owner_cl,suppressor_cl', [(10,10),(10,15),(15,10)])
def test_source_scoped_suppression_uses_only_the_printed_thirty_foot_cushion(tmp_path, monkeypatch, feet, owner_cl, suppressor_cl):
    cold, table, mid = game(tmp_path, monkeypatch, [WINGS], dc=1, speed=feet, cl=owner_cl, other_cl=suppressor_cl,
        other=['TAL_VOID_ERODE_TECHNIQUE','TAL_VOID_RETURN_TO_ZERO'])
    turn(table, mid, A)
    play(cold, table, mid, 'Wingless Ascent', picks={'choice:needle.void_return_to_zero': None})
    turn(table, mid, B)
    turn(table, mid, A, {'choice:needle.seraphic.wingless_mode': 'ascending'})
    current = cold()._load_session(mid).engine
    move = next(c for c in current.legal_candidates() if c.kind == 'MOVE' and c.destination
                and (c.destination.x,c.destination.y,c.destination.z) == (3,6,feet//5))
    settle(table, mid, move.candidate_id)
    before = engine(cold, mid).state.actors[A].current_hp
    # A real enemy Reaction suppresses the newly activated root while the
    # previously chosen Beat is carrying the molter in open air, on A's turn.
    current, prompts = play(cold, table, mid, 'Wingless Ascent')
    assert any('Wingless Ascent' in str(p) for p in prompts)
    assert current.state.actors[A].position.z == 0
    falls = [e for e in current.events if e.event_type == 'MOVEMENT_COMMITTED' and e.actor_id == A
             and e.payload.get('fall_distance_ft')]
    cushion = 30 if suppressor_cl >= owner_cl else 0
    assert sum(e.payload['fall_distance_ft'] for e in falls) == max(0,feet-cushion)
    assert (current.state.actors[A].current_hp < before) is (feet > cushion)
    assert current.state.actors[A].active


@pytest.mark.parametrize('proficiency,legal', [('longsword',False),('herbalism kit',True),('instrument: Reed funerary flute',True)])
def test_ritualist_record_keeps_its_printed_tool_boundary(tmp_path, monkeypatch, proficiency, legal):
    lineage = covenant()
    lineage.update(offices=['Warrior','Ritualist','Wayfarer'], ritual_proficiency=proficiency)
    if legal:
        cold, table, mid = game(tmp_path, monkeypatch, [COUNCIL,POSSESSION], owner_record={'covenant':lineage})
        assert ss.read(engine(cold,mid).state.actors[A])['covenant']['ritual_proficiency'] == proficiency
    else:
        with pytest.raises(ValueError, match='ritual tool'):
            game(tmp_path, monkeypatch, [COUNCIL,POSSESSION], owner_record={'covenant':lineage})
