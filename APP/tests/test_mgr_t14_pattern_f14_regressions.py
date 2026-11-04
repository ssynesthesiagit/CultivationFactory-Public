"""Owned Pattern Layers and Poison survive native construction and table entry."""
import pytest

from combat.ext import formations
from combat.factory_compiler import compile_character
from combat.gate4_context import build_decision_context
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.worker2_support import OWNER, FOE, settle, turn

BINDING = 'tianxia.talent.formations.binding_array'
SEALING = 'tianxia.talent.formations.sealing_gate_pattern'
ELEMENTAL = 'tianxia.talent.formations.elemental_killing_array'
KIT = {'starting_kit': {'items': [{'item_id': 'tianxia.mortal.gear.chalk', 'quantity': 1, 'name': 'Chalk'}]}}


def game(tmp_path, talents, *, patterns=None):
    service = CombatService(ROOT, tmp_path)
    owner = sheet(['FORMATIONS_BASE_SET_ARRAY', *talents], cl=5, kit=KIT)
    if patterns is not None:
        owner.setdefault('spheres_and_talents', {})['formation_patterns'] = list(patterns)
    bundles = [compile_character(owner, actor_id=OWNER), compile_character(sheet([], cl=5), actor_id=FOE)]
    arena = {'display_name': 'F14 map', 'stable_id': 'construction:f14', 'width_squares': 20, 'height_squares': 15,
             'square_size_ft': 5, 'starting_positions': {}, 'terrain_regions': []}
    state = service.journeys.create(bundles, arena, {OWNER: {'x': 3, 'y': 6}, FOE: {'x': 6, 'y': 6}}, {OWNER: 30, FOE: 30})
    jid = state['journey_id']

    def cold():
        return CombatService(ROOT, tmp_path)

    def act(kind, payload, aid=OWNER):
        s = cold().journey_state(jid)
        after = cold().journey_act(jid, s['revision'], aid, kind, payload)
        assert cold().journeys.replay(jid)['status'] == 'PASS'
        return after

    return cold, jid, act


def installed_array(engine, pattern):
    zone, = formations.arrays(engine, OWNER)
    record = formations.record(zone)
    assert record['layers'] == [pattern]
    assert record['mode'] == 'prepared'
    assert len(record['nodes']) == 3
    parts = formations.objects_of(engine, zone)
    assert len(parts) == 4
    assert {p.object_kind for p in parts} == {'FORMATION_EYE', 'FORMATION_NODE'}
    assert all(p.owner_id == OWNER and not p.destroyed for p in parts)
    assert (zone.center.x, zone.center.y) == (4, 6)
    assert not zone.concentration_link
    return zone


@pytest.mark.parametrize('talent,pattern,conditions', [
    (BINDING, 'binding', {'condition:typed.restrained', 'condition:typed.reaction_denied'}),
    (SEALING, 'sealing_gate', {'condition:typed.cannot_teleport', 'condition:typed.formation_teleport_dis'}),
])
@pytest.mark.parametrize('listed', [False, True], ids=['learn-first-basic', 'listed-basic'])
def test_owned_pattern_talent_survives_first_basic_pattern_for_human_and_ai(tmp_path, talent, pattern, conditions, listed):
    cold, jid, act = game(tmp_path, [talent], patterns=['locking_gate'] if listed else None)
    if not listed:
        options = cold().journeys.load(jid).menu(OWNER)['options']
        learn, = [r for r in options if r['id'] == 'learn_pattern:locking_gate']
        state = act(learn['kind'], learn['payload'])
        assert state['actors'][OWNER]['construction_learning']['pattern'] == 'locking_gate'
    before = cold().journey_state(jid)['actors'][OWNER]['resources']['resource:core.qi']
    state = act('prepare_array', {'pattern': pattern, 'center': {'x': 4, 'y': 6}, 'site': '', 'damage_type': 'force'})
    assert state['actors'][OWNER]['constructed_patterns'][-1]['pattern'] == pattern
    assert state['actors'][OWNER]['resources']['resource:core.qi'] == before - 3
    result = cold().journey_start_combat(jid, state['revision'], {OWNER: 'a', FOE: 'b'})
    mid = result['match_id']
    service = cold()
    table = TabletopService(service, tmp_path)
    turn(table, mid, OWNER)
    # A new service must rebuild the installed zone, Eye, Nodes and both menus.
    service = cold()
    session = service._load_session(mid)
    engine = session.engine
    installed_array(engine, pattern)
    contracts = {b['actor_id']: b.get('construction_contract', {}) for b in engine.typed_bundle_documents}
    assert pattern in contracts[OWNER]['talent_patterns']
    assert pattern not in contracts.get(FOE, {}).get('talent_patterns', [])
    assert not any(a.owner_id == FOE and a.parameters.get('pattern') == pattern for a in engine.action_catalog.values())
    policy, _ = service.policies.for_actor(OWNER)
    legal = list(engine.legal_candidates())
    ai = list(build_decision_context(engine, policy, for_ai=True).legal_candidates)
    ai_ids = {c.candidate_id for c in ai}
    for kind in ('set', 'pulse'):
        rows = [c for c in legal if (a := engine.action_catalog.get(c.source_definition_id))
                and a.parameters.get('formation') == kind and a.parameters.get('pattern') == pattern]
        assert rows, kind
        if kind == 'set':
            # A CELL ability reaches an AI seat as one lazy placement root, never as
            # an eager row per square; an offered root must also carry its own
            # evaluated placement. An installed array is the one documented case
            # where the built-in AI keeps its restraint and does not re-set the
            # same technique (combat/ext/ai_restraint.py), so that root is marked
            # placement_ai_unavailable for the AI only; the player keeps the choice.
            roots = {c.source_definition_id: c for c in ai if c.metadata.get('placement_picker')}
            for source in {c.source_definition_id for c in rows}:
                root = roots[source]
                if not root.metadata.get('placement_ai_unavailable'):
                    assert root.metadata.get('placement_evaluation')
        else:
            assert {c.candidate_id for c in rows} <= ai_ids, 'an owned Pulse stays a concrete AI choice'
    pulse = next(c for c in legal if c.target_ids == (FOE,) and
                 engine.action_catalog.get(c.source_definition_id) and
                 engine.action_catalog[c.source_definition_id].parameters.get('formation') == 'pulse' and
                 engine.action_catalog[c.source_definition_id].parameters.get('pattern') == pattern)
    resources = dict(engine.state.actors[OWNER].resources)
    sequence = engine.state.event_sequence
    settle(TabletopService(service, tmp_path), mid, pulse.candidate_id)
    session = cold()._load_session(mid)
    engine = session.engine
    installed_array(engine, pattern)
    assert engine.state.actors[OWNER].resources == resources
    assert not engine.state.actors[OWNER].bonus_action_available
    assert engine.state.actors[FOE].turn_flags['formation_round_pulse:' + pattern] == engine.state.round_number
    assert any(c.condition_id in conditions for c in engine.state.actors[FOE].conditions.values())
    assert any(e.event_type == 'SAVE_ROLLED' and e.actor_id == FOE and e.sequence > sequence for e in engine.events)
    assert session.verify()['status'] == 'PASS'
    assert session.mechanical.replay()['status'] == 'PASS'


def test_elemental_killing_array_poison_admits_places_pays_and_replays(tmp_path):
    # No listed pattern: this scenario actually exercises Formation Training.
    cold, jid, act = game(tmp_path, [ELEMENTAL])
    options = cold().journeys.load(jid).menu(OWNER)['options']
    learn, = [r for r in options if r['id'] == 'learn_pattern:killing_line']
    act(learn['kind'], learn['payload'])
    before = cold().journey_state(jid)['actors'][OWNER]['resources']['resource:core.qi']
    cold().journey_admit(jid, cold().journey_state(jid)['revision'], OWNER, 'formation_damage_type',
        {'damage_type': 'poison', 'source_logic': 'The Elemental Killing Array poison damage expression is installed.'},
        gm=True, reason='GM source declaration: Elemental Killing Array poison')
    assert cold().journeys.replay(jid)['status'] == 'PASS'
    state = act('prepare_array', {'pattern': 'killing_line', 'center': {'x': 4, 'y': 6}, 'site': '', 'damage_type': 'poison'})
    record = state['actors'][OWNER]['constructed_patterns'][-1]
    assert record['damage_type'] == 'poison'
    assert state['actors'][OWNER]['resources']['resource:core.qi'] == before - 3
    reloaded = cold().journey_state(jid, viewer_id=OWNER)['actors'][OWNER]['constructed_patterns'][-1]
    assert reloaded['damage_type'] == 'poison'
    assert 'constructed_patterns' not in cold().journey_state(jid, viewer_id=FOE)['actors'][OWNER]
    result = cold().journey_start_combat(jid, state['revision'], {OWNER: 'a', FOE: 'b'})
    session = cold()._load_session(result['match_id'])
    zone = installed_array(session.engine, 'killing_line')
    assert formations.record(zone)['damage_type'] == 'poison'
    # Inspect the live trigger, not merely the saved construction request.
    assert any(effect.get('damage_types') == ['poison']
               for trigger in zone.trigger_profile['triggers'] for effect in trigger['effects'])
    assert session.engine.state.actors[OWNER].resources['resource:core.qi'] == before - 3
    assert session.verify()['status'] == 'PASS'
    assert session.mechanical.replay()['status'] == 'PASS'
