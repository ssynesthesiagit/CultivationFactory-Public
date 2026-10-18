"""F14 regressions: owned pattern talents and Elemental Killing Array's Poison, through the native journey and combat paths."""
from hashlib import sha256

from combat.ext import formations
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.ext.pattern_construction import learned_patterns
from tests.h1_support import ROOT, sheet
from tests.worker2_support import OWNER, FOE


BINDING = 'tianxia.talent.formations.binding_array'
ELEMENTAL = 'tianxia.talent.formations.elemental_killing_array'
CHALK = {'starting_kit': {'items': [{'item_id': 'tianxia.mortal.gear.chalk', 'name': 'Chalk', 'quantity': 1}]}}


def setup(tmp_path, owner_talents, *, listed=None, cl=5):
    doc = sheet(['FORMATIONS_BASE_SET_ARRAY', *owner_talents], cl=cl, kit=CHALK)
    if listed is not None:
        doc['spheres_and_talents']['formation_patterns'] = list(listed)
    foe = sheet([], cl=cl, kit=CHALK)
    bundles = [compile_character(doc, actor_id=OWNER), compile_character(foe, actor_id=FOE)]
    arena = {'display_name': 'F14 map', 'stable_id': 'f14:patterns', 'width_squares': 14, 'height_squares': 12,
             'square_size_ft': 5, 'starting_positions': {}, 'terrain_regions': []}
    service = CombatService(ROOT, tmp_path)
    created = service.journeys.create(bundles, arena, {OWNER: {'x': 3, 'y': 6}, FOE: {'x': 10, 'y': 6}},
                                      {OWNER: 30, FOE: 30}, {OWNER: 'MANUAL', FOE: 'MANUAL'})
    return service, created['journey_id']


def act(service, jid, kind, payload):
    return service.journey_act(jid, service.journey_state(jid)['revision'], OWNER, kind, payload)


def test_owned_pattern_talent_is_usable_by_human_and_ai_after_first_basic_pattern(tmp_path):
    # No recorded formation_patterns: the first Basic Pattern is learned on the journey, the owned talent stays usable.
    service, jid = setup(tmp_path, [BINDING])
    options = service.journey_menu(jid, OWNER)['options']
    assert not any(r['kind'] == 'learn_construction_pattern' and r['payload'] == {'pattern': 'binding'} for r in options)
    state = act(service, jid, 'learn_construction_pattern', {'pattern': 'locking_gate'})
    assert state['actors'][OWNER]['construction_learning']['pattern'] == 'locking_gate'
    state = act(service, jid, 'prepare_array', {'pattern': 'binding', 'center': {'x': 3, 'y': 6}, 'site': '', 'damage_type': 'force'})
    assert state['actors'][OWNER]['constructed_patterns'][-1]['payload']['spec']['name'] == 'Binding Array'
    cold = CombatService(ROOT, tmp_path)
    assert cold.journeys.replay(jid)['status'] == 'PASS'
    result = cold.journey_start_combat(jid, cold.journey_state(jid)['revision'], {OWNER: 'a', FOE: 'b'})
    engine = cold._load_session(result['match_id']).engine
    # The human Set gate and the AI candidate gate both consult learned_patterns.
    known = learned_patterns(engine, engine.state.actors[OWNER])
    assert 'binding' in known and 'locking_gate' in known
    assert 'binding' not in learned_patterns(engine, engine.state.actors[FOE])


def test_elemental_killing_array_poison_admits_places_pays_and_replays(tmp_path):
    service, jid = setup(tmp_path, [ELEMENTAL], listed=['killing_line'])
    before = service.journey_state(jid)['actors'][OWNER]['resources']['resource:core.qi']
    admitted = service.journey_admit(jid, service.journey_state(jid)['revision'], OWNER, 'formation_damage_type',
        {'damage_type': 'poison', 'source_logic': 'Elemental Killing Array: the sphere poison damage expression'},
        gm=True, reason='Actual recorded source for this test scene')
    assert admitted['revision'] > 0
    state = act(service, jid, 'prepare_array', {'pattern': 'killing_line', 'center': {'x': 3, 'y': 6}, 'site': '', 'damage_type': 'poison'})
    record = state['actors'][OWNER]['constructed_patterns'][-1]
    assert record['damage_type'] == 'poison'
    assert state['actors'][OWNER]['resources']['resource:core.qi'] == before - 3
    cold = CombatService(ROOT, tmp_path)
    assert cold.journeys.replay(jid)['status'] == 'PASS'
    reloaded = cold.journey_state(jid)['actors'][OWNER]['constructed_patterns'][-1]
    assert reloaded['damage_type'] == 'poison'
    assert 'poison' in formations.killing_types_for(['elemental_killing_array'])
    result = cold.journey_start_combat(jid, cold.journey_state(jid)['revision'], {OWNER: 'a', FOE: 'b'})
    assert cold._load_session(result['match_id']).mechanical.replay()['status'] == 'PASS'
