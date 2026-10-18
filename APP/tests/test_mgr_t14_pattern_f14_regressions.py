"""F14 regressions (Sol F13R review): owned Pattern talents survive the first Basic Pattern, and Elemental Killing
Array keeps Poison reachable through admission, placement, payment and cold reload."""
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from tests.h1_support import ROOT, sheet
from tests.worker2_support import OWNER, FOE

BINDING = 'tianxia.talent.formations.binding_array'
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
    state = service.journeys.create(bundles, arena, {OWNER: {'x': 3, 'y': 6}, FOE: {'x': 10, 'y': 6}}, {OWNER: 30, FOE: 30})
    jid = state['journey_id']

    def cold():
        return CombatService(ROOT, tmp_path)

    def act(kind, payload, aid=OWNER):
        s = cold().journey_state(jid)
        after = cold().journey_act(jid, s['revision'], aid, kind, payload)
        assert cold().journeys.replay(jid)['status'] == 'PASS'
        return after

    return cold, jid, act


def test_owned_pattern_talent_survives_first_basic_pattern_for_human_and_ai(tmp_path):
    cold, jid, act = game(tmp_path, [BINDING])
    options = cold().journeys.load(jid).menu(OWNER)['options']
    learn, = [r for r in options if r['id'] == 'learn_pattern:locking_gate']
    state = act(learn['kind'], learn['payload'])
    assert state['actors'][OWNER]['construction_learning']['pattern'] == 'locking_gate'
    state = act('prepare_array', {'pattern': 'binding', 'center': {'x': 4, 'y': 6}, 'site': '', 'damage_type': 'force'})
    assert state['actors'][OWNER]['constructed_patterns'][-1]['pattern'] == 'binding'
    result = cold().journey_start_combat(jid, cold().journey_state(jid)['revision'], {OWNER: 'a', FOE: 'b'})
    session = cold()._load_session(result['match_id'])
    assert session.mechanical.replay()['status'] == 'PASS'
    # The owned talent pattern is part of the sealed construction contract for the owner only (human and AI seats alike).
    contracts = {b['actor_id']: b['construction_contract'] for b in session.engine.typed_bundle_documents}
    assert 'binding' in contracts[OWNER]['talent_patterns']
    assert 'binding' not in contracts[FOE].get('talent_patterns', [])


def test_elemental_killing_array_poison_admits_places_pays_and_replays(tmp_path):
    cold, jid, act = game(tmp_path, [ELEMENTAL], patterns=['killing_line'])
    before = cold().journey_state(jid)['actors'][OWNER]['resources']['resource:core.qi']
    state = cold().journey_admit(jid, cold().journey_state(jid)['revision'], OWNER, 'formation_damage_type',
        {'damage_type': 'poison', 'source_logic': 'The Elemental Killing Array poison damage expression is installed.'},
        gm=True, reason='GM source declaration: Elemental Killing Array poison')
    assert cold().journeys.replay(jid)['status'] == 'PASS'
    state = act('prepare_array', {'pattern': 'killing_line', 'center': {'x': 4, 'y': 6}, 'site': '', 'damage_type': 'poison'})
    record = state['actors'][OWNER]['constructed_patterns'][-1]
    assert record['damage_type'] == 'poison'
    assert state['actors'][OWNER]['resources']['resource:core.qi'] < before
    reloaded = cold().journey_state(jid)['actors'][OWNER]['constructed_patterns'][-1]
    assert reloaded['damage_type'] == 'poison'
    result = cold().journey_start_combat(jid, cold().journey_state(jid)['revision'], {OWNER: 'a', FOE: 'b'})
    assert cold()._load_session(result['match_id']).mechanical.replay()['status'] == 'PASS'
