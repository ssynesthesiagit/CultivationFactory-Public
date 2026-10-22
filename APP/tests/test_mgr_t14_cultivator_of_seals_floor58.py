"""Native acquisition and persisted seal lifecycle regressions; no live models."""
from copy import deepcopy
import json
from pathlib import Path
from zipfile import ZipFile

import pytest

from combat.factory_compiler import compile_character
from combat.feature_access import acquire
from combat.gate2_runtime_models import ActionIntent
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.ext.qi_sealing_chains import LEVELS, MINOR, MARK, SOURCE, PRISON, EDICT, SEAL
SHEET = {
    "identity": {"proficiency_bonus": 4, "cultivation_level": 10, "path": "Qi Cultivation", "key_ability": "CON"},
    "ability_scores_and_statistics": {
        "abilities": [{"ability": a, "score": 14, "modifier": 2} for a in ("STR", "DEX", "CON", "INT", "WIS", "CHA")],
        "primary_resource": {"name": "Qi", "maximum": 30}, "armor_class": {"base_value": 14}, "hit_points": {"maximum": 60},
        "speed": {"walking_ft": 30}, "technique_save_dc": 30, "technique_attack_bonus": 8,
    },
    "spheres_and_talents": {"sphere_record_ids": ["tianxia.sphere.ash"],
                            "learned_talent_record_ids": ["ASH_BASE_ASHFALL", "ASH_TAL_SOOT_IN_LUNGS"]},
}
# A synthetic sheet (same literal as tests/test_zones.py) so this file stays public-CI safe.

ROOT = Path(__file__).resolve().parents[1]
PATH = 'tianxia.path.qi_cultivation'
PARENT = 'tianxia.subpath.qi.cultivator_of_seals'
ME, FOE = FACTORY_ACTOR_PREFIX + 'seal-owner', FACTORY_ACTOR_PREFIX + 'seal-target'


def acquired_sheet(cl=18, *, acquired=True):
    sheet = deepcopy(SHEET)
    sheet['identity'].update(cultivation_level=cl, name='Seal Cultivator')
    sheet['spheres_and_talents'] = {}
    sheet['path_and_subpath'] = {'path_record_ids': [PATH],
        'subpaths': [{'subpath_id': PARENT, 'owning_path_id': PATH}]}
    sheet['ability_scores_and_statistics']['technique_save_dc'] = 50
    if acquired:
        for feature, minimum in LEVELS.items():
            if minimum <= cl:
                sheet = acquire(sheet, feature, {'kind': 'scripture', 'reference': 'Test campaign: granted Seals scripture',
                    'classification': 'Restricted Scripture'})
    return sheet


def install(root, name, sheet):
    folder = root / 'portable_characters' / name
    folder.mkdir(parents=True)
    with ZipFile(folder / 'current.zip', 'w') as archive:
        archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(sheet))


def setup(tmp_path, *, target_cl=10, target_talents=(), target_saves=None):
    install(tmp_path, 'seal-owner', acquired_sheet())
    target = deepcopy(SHEET)
    target['identity'].update(name='Target', cultivation_level=target_cl)
    target['spheres_and_talents'] = {}
    target['path_and_subpath'] = {'path_record_ids': [PATH]}
    if target_talents:
        target['spheres_and_talents'] = {'sphere_record_ids': ['tianxia.sphere.ash', 'tianxia.sphere.air'],
            'learned_talent_record_ids': list(target_talents)}
    if target_saves:
        target['ability_scores_and_statistics']['saving_throws'] = target_saves
    install(tmp_path, 'seal-target', target)
    service = CombatService(ROOT, tmp_path)
    arena = service.tabletop_maps.save({'display_name': 'Seal Test', 'width_squares': 16, 'height_squares': 12,
        'starts': {'team1': [[4, 5]], 'team2': [[5, 5]]},
        'objects': [{'id': 1, 'kind': 'door', 'x': 4, 'y': 6, 'size': 'medium',
                     'interaction': 'simple_door',
                     'height_ft': 5,
                     'door_open': 0, 'door_locked': 0, 'door_jammed': 0}]})
    view = service.create_factory_match(project_ids=['seal-owner'], opponent_actor_ids=[FOE],
        match_seed='SEAL-NATIVE', arena_id='battlefield:map.' + arena['map_id'],
        control_modes={ME: 'LOCAL_AUTO', FOE: 'LOCAL_AUTO'})
    session = service._load_session(view['match_id'])
    for _ in range(4):
        if session.engine.state.current_actor_id == ME:
            break
        act(session, next(c for c in session.engine.legal_candidates() if c.kind.value == 'END_TURN'))
    assert session.engine.state.current_actor_id == ME
    return service, session


def act(session, candidate, provider=None):
    session.submit_intent(ActionIntent(intent_id='seal-test:' + str(session.engine.state.state_version),
        candidate_id=candidate.candidate_id, decision_id=candidate.decision_id,
        state_version=candidate.state_version, actor_id=candidate.actor_id,
        target_ids=candidate.target_ids, destination=candidate.destination),
        primary_decision_record=None, reaction_provider=provider)


def test_ordinary_action_payload_cannot_submit_owner_table_fact(tmp_path):
    service, session = setup(tmp_path)
    context = service._decision_model(session)
    candidate = context.legal_candidates[0]
    payload = {
        'candidate_id': candidate.candidate_id,
        'decision_id': candidate.decision_id,
        'state_version': candidate.state_version,
        'actor_id': candidate.actor_id,
        'target_ids': list(candidate.target_ids),
        'destination': candidate.destination.model_dump(mode='json') if candidate.destination else None,
        'table_fact': {'fabricated': True},
    }
    with pytest.raises(ValueError, match='owner-only command'):
        service._intent_from_payload(context, payload)


def test_native_restricted_progression_requires_access_and_respects_level():
    denied = compile_character(acquired_sheet(acquired=False), actor_id=ME)
    assert not [a for a in denied['action_catalog'] if (a['parameters'].get('typed') or {}).get('source') in LEVELS]
    low = compile_character(acquired_sheet(6), actor_id=ME)
    sources = {(a['parameters'].get('typed') or {}).get('source') for a in low['action_catalog']}
    assert {MINOR, SOURCE} <= sources
    assert not {MARK, PRISON, EDICT} & sources
    wrong = acquired_sheet()
    wrong['path_and_subpath']['subpaths'][0]['owning_path_id'] = 'tianxia.path.body_refining'
    wrong['path_and_subpath']['path_feature_record_ids'] = []
    assert not [a for a in compile_character(wrong, actor_id=ME)['action_catalog']
                if (a['parameters'].get('typed') or {}).get('source') in LEVELS]


def test_native_source_numbers_respect_the_effective_path_level():
    sheet = acquired_sheet()
    sheet['identity']['effective_path_cls'] = {PATH: 10}
    bundle = compile_character(sheet, actor_id=ME)
    rows = [(a['parameters'].get('typed') or {}) for a in bundle['action_catalog']
            if (a['parameters'].get('typed') or {}).get('source') in LEVELS]
    assert {row['source'] for row in rows} == {MINOR, SOURCE, MARK}
    assert all(row['numbers']['cl'] == 10 for row in rows)


@pytest.mark.parametrize('feature,cost', [(SOURCE, 3), (MINOR, 1), (MARK, 5), (PRISON, 6), (EDICT, 8)])
def test_native_source_activation_commits_and_cold_reloads(tmp_path, feature, cost):
    service, session = setup(tmp_path)
    engine = session.engine
    before = engine.state.actors[ME].resources['resource:core.qi']
    candidates = [c for c in engine.legal_candidates() if c.source_definition_id in engine.action_catalog
        and (engine.action_catalog[c.source_definition_id].parameters.get('typed') or {}).get('source') == feature
        and (feature == MINOR or c.target_ids == (FOE,))
        and (feature != MARK or not c.source_definition_id.endswith(('.meridian', '.core')))]
    assert candidates, {'objects': [o.model_dump() for o in engine.state.objects.values()],
                        'actions': [a.model_dump() for a in engine.action_catalog.values() if
                                    (a.parameters.get('typed') or {}).get('source') == feature]}
    act(session, candidates[0])
    reloaded = CombatService(ROOT, tmp_path)._load_session(session.match_id)
    assert reloaded.engine.state.actors[ME].resources['resource:core.qi'] == before - cost
    state = reloaded.engine.state
    if feature == SOURCE:
        assert any(c.data.get('qi5_chain') for c in state.actors[FOE].conditions.values())
        assert reloaded.engine._effective_speed(state.actors[FOE]) == 0
    else:
        bound = [c for a in state.actors.values() for c in a.conditions.values()
                 if c.condition_id == SEAL and c.data.get('seal_feature') == feature]
        assert len(bound) == (3 if feature == EDICT else 1)
        anchors = [o for o in state.objects.values() if (o.component or {}).get('seal_feature') == feature]
        assert len(anchors) == len(bound)
        assert all(o.current_hp > 0 and o.component['source_cl'] == 18 for o in anchors)
        if feature in {PRISON, EDICT}:
            assert reloaded.engine._effective_speed(state.actors[FOE]) == 0


def test_lock_seal_stops_real_door_interaction_after_cold_reload(tmp_path):
    _, session = setup(tmp_path)
    engine = session.engine
    seal = next(c for c in engine.legal_candidates() if c.source_definition_id in engine.action_catalog
        and (engine.action_catalog[c.source_definition_id].parameters.get('typed') or {}).get('source') == MINOR)
    act(session, seal)
    session = CombatService(ROOT, tmp_path)._load_session(session.match_id)
    opening = next(c for c in session.engine.legal_candidates() if c.source_definition_id == 'system:door.open.free')
    act(session, opening)
    reloaded = CombatService(ROOT, tmp_path)._load_session(session.match_id)
    door = reloaded.engine.state.objects['object:map.1']
    assert door.component['door_open'] == 0


@pytest.mark.parametrize('target_cl,repeats', [(16, 0), (17, 0), (18, 1)])
def test_prison_keeps_omitted_band_legal_without_inventing_a_repeat_save(tmp_path, target_cl, repeats):
    _, session = setup(tmp_path, target_cl=target_cl)
    engine = session.engine
    candidate = next(c for c in engine.legal_candidates() if c.target_ids == (FOE,)
        and c.source_definition_id in engine.action_catalog
        and (engine.action_catalog[c.source_definition_id].parameters.get('typed') or {}).get('source') == PRISON)
    act(session, candidate)
    session = CombatService(ROOT, tmp_path)._load_session(session.match_id)
    before = sum(e.event_type == 'SAVE_ROLLED' and e.actor_id == FOE for e in session.engine.events)
    act(session, next(c for c in session.engine.legal_candidates() if c.kind.value == 'END_TURN'))
    assert session.engine.state.current_actor_id == FOE
    act(session, next(c for c in session.engine.legal_candidates() if c.kind.value == 'END_TURN'))
    reloaded = CombatService(ROOT, tmp_path)._load_session(session.match_id)
    after = sum(e.event_type == 'SAVE_ROLLED' and e.actor_id == FOE for e in reloaded.engine.events)
    assert after - before == repeats


def scoped_answers(answer):
    """Answer the seal scope question with ``answer`` (None declines it), pay
    Break the Seal's price from the Qi pool, and record every request so the
    test can verify who was asked."""
    from combat.gate2_runtime_models import ReactionDecision
    seen = []

    def provider(request):
        seen.append(request)
        source = request['reaction_source_id']
        picked = {'choice:needle.qi_seal.scope': answer, 'choice:needle.qi_seal.break_price': 'resource:core.qi'}.get(source)
        if picked is None:
            return None, None
        return ReactionDecision(checkpoint=request['checkpoint'], reactor_id=request['reactor_id'],
            reaction_source_id=source, selection='USE', option_ids=(picked,)), None

    return provider, seen


def test_break_core_seal_asks_its_source_for_the_meridian_downgrade_scope(tmp_path):
    """Lead ruling (MGR-T14): the first successful Break the Seal against a Core
    Mark asks the seal's source to pick one printed Meridian scope (no Meridian
    Requirement); that scope replaces the Core scope until the start of the
    target's next turn, then the Core scope returns with its success count
    intact, so a second success ends the Mark."""
    _, session = setup(tmp_path, target_talents=('ASH_BASE_ASHFALL', 'AIR_BASE_WIND_LASH'), target_saves={'CHA': 60})

    def native(active_session, feature, grade=None):
        engine = active_session.engine
        return next(c for c in engine.legal_candidates() if c.source_definition_id in engine.action_catalog
            and (engine.action_catalog[c.source_definition_id].parameters.get('typed') or {}).get('source') == feature
            and c.target_ids == (FOE,)
            and (grade is None or c.source_definition_id.endswith('.' + grade)))

    def end_turn(active_session):
        return next(c for c in active_session.engine.legal_candidates() if c.kind.value == 'END_TURN')

    def mark_of(active_session):
        return next(c for a in active_session.engine.state.actors.values() for c in a.conditions.values()
                    if c.condition_id == SEAL and c.data.get('seal_feature') == MARK)

    def offered(active_session):
        return {c.source_definition_id for c in active_session.engine.legal_candidates()}

    # Chains of Qi fails its Dexterity save and Prepares the target for Sealing.
    act(session, native(session, SOURCE))
    session = CombatService(ROOT, tmp_path)._load_session(session.match_id)
    act(session, end_turn(session))
    act(session, end_turn(session))
    assert session.engine.state.current_actor_id == ME

    # The Core Seal's source names 'All Spheres known by the target'.
    provider, placement_asked = scoped_answers('all_spheres')
    act(session, native(session, MARK, 'core'), provider)
    session = CombatService(ROOT, tmp_path)._load_session(session.match_id)
    mark = mark_of(session)
    assert mark.data['grade'] == 'core' and mark.data['scope'] == {'kind': 'all_spheres', 'value': ''}
    assert {r['reactor_id'] for r in placement_asked if r['reaction_source_id'] == 'choice:needle.qi_seal.scope'} == {ME}
    act(session, end_turn(session))

    # Pre-break: the Core scope blocks every Sphere-sourced action of the target.
    ash_id = next(a.source_definition_id for a in session.engine.action_catalog.values()
                  if a.owner_id == FOE and a.display_name.startswith('Ashfall'))
    lash_id = next(a.source_definition_id for a in session.engine.action_catalog.values()
                   if a.owner_id == FOE and a.display_name.startswith('Wind Lash'))
    assert session.engine.state.current_actor_id == FOE
    assert not {ash_id, lash_id} & offered(session)
    assert 'system:qi_seal_break' in offered(session)
    before_cp = session.engine.state.actors[FOE].resources['resource:core.qi']

    # First successful Break the Seal: the price is paid, then the SOURCE picks
    # the replacement Meridian scope ('All weapon-delivered cultivation techniques').
    provider, break_asked = scoped_answers('weapon_delivery')
    act(session, next(c for c in session.engine.legal_candidates() if c.source_definition_id == 'system:qi_seal_break'), provider)
    session = CombatService(ROOT, tmp_path)._load_session(session.match_id)
    foe = session.engine.state.actors[FOE]
    mark = mark_of(session)
    assert mark.data['break_successes'] == 1
    assert mark.data['downgrade_scope'] == {'kind': 'weapon_delivery', 'value': ''}
    assert mark.data['downgraded_until_turn'] == foe.turns_started + 1
    assert foe.resources['resource:core.qi'] == before_cp - 4  # the chosen 4-CP price was actually paid
    scope_asks = [r for r in break_asked if r['reaction_source_id'] == 'choice:needle.qi_seal.scope']
    assert scope_asks and {r['reactor_id'] for r in scope_asks} == {ME}
    # During the window the Core scope is switched off: the same gate the engine
    # consults for candidate listing reports Sphere actions no longer suppressed.
    # (Break the Seal spent the target's Action, so sphere actions - Action
    # economy - cannot be listed again until its next turn starts, by which time
    # the window has closed; the post-window listing below checks that turn.)
    from combat.ext.qi_sealing_chains import current_scope, suppressed_activation
    foe = session.engine.state.actors[FOE]
    assert suppressed_activation(session.engine, foe, {'source_kind': 'Sphere'}) is False
    assert current_scope(foe, mark) == {'kind': 'weapon_delivery', 'value': ''}
    # ... and the chosen Meridian scope itself is now the one enforced.
    assert suppressed_activation(session.engine, foe, {'weapon_delivery': True}) is True

    # The window survives the other creatures' turns...
    act(session, end_turn(session))
    assert session.engine.state.current_actor_id == ME
    assert mark_of(session).data.get('downgrade_scope') == {'kind': 'weapon_delivery', 'value': ''}
    act(session, end_turn(session))

    # ...and closes at the start of the target's next turn: the Core scope
    # enforces again, with the success count untouched.
    assert session.engine.state.current_actor_id == FOE
    mark = mark_of(session)
    assert 'downgrade_scope' not in mark.data and 'downgraded_until_turn' not in mark.data
    assert mark.data['break_successes'] == 1
    assert not {ash_id, lash_id} & offered(session)

    # The second successful Break the Seal ends the Mark outright.
    provider, second_asked = scoped_answers(None)
    act(session, next(c for c in session.engine.legal_candidates() if c.source_definition_id == 'system:qi_seal_break'), provider)
    session = CombatService(ROOT, tmp_path)._load_session(session.match_id)
    assert not [c for a in session.engine.state.actors.values() for c in a.conditions.values()
                if c.condition_id == SEAL and c.data.get('seal_feature') == MARK]
    assert not [r for r in second_asked if r['reaction_source_id'] == 'choice:needle.qi_seal.scope']
    # With the Mark gone the suppression gate no longer vetoes Sphere actions
    # (the Action is spent, so sphere actions cannot be listed on this commit).
    assert suppressed_activation(session.engine, session.engine.state.actors[FOE], {'source_kind': 'Sphere'}) is False


class _Cond:
    def __init__(self, data, instance_id='c1', source_actor_id='actor:src'):
        self.condition_id = SEAL
        self.data = {'seal_feature': MARK, **data}
        self.instance_id = instance_id
        self.source_actor_id = source_actor_id
        self.source_definition_id = 'src.def'


class _Actor:
    def __init__(self, entity_id, turns_started=0):
        self.entity_id = entity_id
        self.turns_started = turns_started
        self.conditions = {}


class _Engine:
    def __init__(self, actors):
        self.state = type('S', (), {'actors': {a.entity_id: a for a in actors}, 'objects': {}})()
        self.updates = []

    def _update_condition_data(self, holder, condition, data, source, **_):
        condition.data = data
        self.updates.append(condition.instance_id)

    def _remove_condition_instance(self, holder, instance_id, source, **_):
        holder.conditions.pop(instance_id, None)


def test_minor_seal_end_choice_names_the_object_not_its_id():
    from combat.ext.qi_sealing_chains import minor_end_label
    engine = _Engine([])
    engine.state.objects['object:map.9'] = type('O', (), {'component': {'name': 'Ironbound Chest'}})()
    label = minor_end_label(engine, _Cond({'object_id': 'object:map.9'}))
    assert label == 'End Minor Seal on Ironbound Chest'
    assert 'object:map.9' not in label


def test_downgrade_window_clears_even_when_a_binding_timer_fires_the_same_pass(monkeypatch):
    from combat.ext import effect_durations
    from combat.ext.qi_sealing_chains import finite_seals
    monkeypatch.setattr(effect_durations, 'due', lambda engine, name, *a, **k: name == 'timer')
    src = _Actor('actor:src', turns_started=3)
    foe = _Actor('actor:foe', turns_started=5)
    timed = _Cond({'deadline': 'timer', 'binding_short': 1, 'owner_turn': 1, 'binding_active': 1},
                  instance_id='timed', source_actor_id='actor:src')
    window = _Cond({'deadline': 'later', 'downgrade_scope': {'kind': 'weapon_delivery', 'value': ''},
                    'downgraded_until_turn': 5, 'scope': {'kind': 'all_spheres', 'value': ''}, 'break_successes': 1},
                   instance_id='window', source_actor_id='actor:src')
    foe.conditions = {'timed': timed, 'window': window}
    engine = _Engine([src, foe])
    finite_seals(engine, foe)
    assert 'downgrade_scope' not in window.data and 'downgraded_until_turn' not in window.data
    assert window.data['break_successes'] == 1 and window.data['scope'] == {'kind': 'all_spheres', 'value': ''}

def test_departed_placer_keeps_core_scope_without_a_meridian_pick(monkeypatch):
    # Break the Seal on a Core Mark whose placer has left the fight: nobody is asked for
    # a Meridian scope, the Core scope stays, and the count is 1 so the next Break ends it.
    from combat.ext import qi_sealing_chains as q
    actor = _Actor('actor:foe', turns_started=2)
    actor.display_name = 'Foe'
    core = _Cond({'seal_feature': MARK, 'grade': 'core', 'break_successes': 0, 'source_pb': 2,
                  'save_dc': 10, 'label': 'Core Mark', 'scope': {'kind': 'all_spheres', 'value': ''}},
                 instance_id='core', source_actor_id='actor:gone')
    actor.conditions = {'core': core}
    engine = _Engine([actor])  # 'actor:gone' is not in state.actors
    engine._roll_save = lambda *a, **k: type('R', (), {'total': 99})()
    engine._spend_resource = lambda *a, **k: None
    engine._commit_damage = lambda *a, **k: None
    asked = []
    monkeypatch.setattr(q, 'downgrade_scope_choice', lambda ctx, chooser: asked.append(chooser) or {})
    monkeypatch.setattr(q, 'choose', lambda ctx, who, key, labels, prompt, preferred=None:
                        'core' if key == 'break_binding' else 'pb')
    monkeypatch.setattr(q, 'seals', lambda engine, subject=None: [(actor, core)])
    from combat.ext import needle
    monkeypatch.setattr(needle, 'numbers_of', lambda engine, actor: {})
    monkeypatch.setattr(q, 'nearby_anchors', lambda engine, actor: [])
    from dataclasses import dataclass
    @dataclass
    class _Ctx:
        engine: object
        actor: object
        source: object
        typed: dict
    ctx = _Ctx(engine, actor, 'src', {'numbers': {}})
    q.release_seal(ctx, {'kind': 'break'})
    assert asked == []
    assert core.data.get('break_successes') == 1
    assert 'downgrade_scope' not in core.data


def test_owner_recorded_circulation_fact_reaches_the_meridian_seal_gate(tmp_path):
    """The table-fact producer is wired through the service, not merely defined.

    Without a record the target is not Prepared for Sealing, so no Meridian Seal
    row exists. One owner-recorded, witnessed circulation fact (an actual table
    procedure the printed requirement allows) makes that row legal, survives a
    cold reload, and stays invisible to the creature that did not observe it.
    """
    from combat.table_facts import records
    service, session = setup(tmp_path)

    def meridian_rows(engine):
        return [c for c in engine.legal_candidates() if c.target_ids == (FOE,)
                and c.source_definition_id in engine.action_catalog
                and (engine.action_catalog[c.source_definition_id].parameters.get('typed') or {}).get('source') == MARK
                and c.source_definition_id.endswith('.meridian')]

    assert meridian_rows(session.engine) == []
    document = {'record_id': 'fact:circulation', 'subject_id': FOE, 'subject_name': 'Target',
        'subject_kind': 'creature', 'position': {'x': 5, 'y': 5},
        'source_reference': 'Test campaign: the Seal Cultivator watched the target circulate Qi',
        'witness_ids': [ME], 'valid_through_round': 10,
        'answers': {'identified_circulation': {'fact': 'Circulation identified', 'category': 'identified_circulation',
            'visible_sign': 'Qi visibly cycles through the target’s meridians', 'source_cl': 18}}}
    service.record_table_fact(session.match_id, fact=document,
                              expected_state_version=session.engine.state.state_version)
    reloaded = CombatService(ROOT, tmp_path)._load_session(session.match_id)
    assert [e.payload['fact']['record_id'] for e in reloaded.engine.events
            if e.event_type == 'TABLE_FACT_RECORDED'] == ['fact:circulation']
    assert set(records(reloaded.engine, reloaded.engine.state.actors[ME])) == {'fact:circulation'}
    assert records(reloaded.engine, reloaded.engine.state.actors[FOE]) == {}
    assert meridian_rows(reloaded.engine)
    assert meridian_rows(session.engine) == []


def test_plain_door_open_and_close_are_unaffected_by_the_object_operation_gate(tmp_path):
    """A door with no seal stays ordinary: the new shared gate is inert.

    Object-operation vetoes only exist for a plug-in-owned object (Minor Seal,
    Source Lock); a plain simple door must still open and close for a character
    who owns no sealing feature.
    """
    _, session = setup(tmp_path)
    act(session, next(c for c in session.engine.legal_candidates()
                      if c.source_definition_id == 'system:door.open.free'))
    session = CombatService(ROOT, tmp_path)._load_session(session.match_id)
    assert session.engine.state.objects['object:map.1'].component['door_open'] == 1
    for _ in range(2):
        act(session, next(c for c in session.engine.legal_candidates() if c.kind.value == 'END_TURN'))
    session = CombatService(ROOT, tmp_path)._load_session(session.match_id)
    assert session.engine.state.current_actor_id == ME
    act(session, next(c for c in session.engine.legal_candidates()
                      if c.source_definition_id == 'system:door.close.free'))
    reloaded = CombatService(ROOT, tmp_path)._load_session(session.match_id)
    assert reloaded.engine.state.objects['object:map.1'].component['door_open'] == 0



def test_denied_door_open_keeps_the_free_object_interaction(tmp_path):
    """Addendum Q3: a Lock Seal denial in door_interaction.interact does not claim the free interaction.

    The denied free open leaves the door closed, does not set the once-per-turn
    free-interaction receipt, does not spend the Action, and keeps the free option on the menu.
    """
    from combat.object_interaction import used
    _, session = setup(tmp_path)
    seal = next(c for c in session.engine.legal_candidates() if c.source_definition_id in session.engine.action_catalog
        and (session.engine.action_catalog[c.source_definition_id].parameters.get('typed') or {}).get('source') == MINOR)
    act(session, seal)
    for _ in range(2):
        act(session, next(c for c in session.engine.legal_candidates() if c.kind.value == 'END_TURN'))
    session = CombatService(ROOT, tmp_path)._load_session(session.match_id)
    assert session.engine.state.current_actor_id == ME
    assert session.engine.state.actors[ME].action_available is True
    act(session, next(c for c in session.engine.legal_candidates() if c.source_definition_id == 'system:door.open.free'))
    session = CombatService(ROOT, tmp_path)._load_session(session.match_id)
    engine = session.engine
    assert engine.state.objects['object:map.1'].component['door_open'] == 0
    assert not used(engine.state.actors[ME])
    assert engine.state.actors[ME].action_available is True
    assert any(c.source_definition_id == 'system:door.open.free' for c in engine.legal_candidates())
