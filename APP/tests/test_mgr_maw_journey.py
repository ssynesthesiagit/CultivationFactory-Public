"""Acquired Maw -> native journey/fight -> explicit scene -> cold replay."""
from copy import deepcopy
import pytest

from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.gate2_rolls import DeterministicRollAuthority
from combat.gate2_runtime_models import DiceSpec
from tests.h1_support import ROOT, sheet
from tests.worker2_support import OWNER, FOE, turn, settle, reload
from tests.test_mgr_maw_native import acquired, burn
from combat.ext.devouring_maw_journey import SOURCE
from combat.ext.devouring_maw import ESSENCE


def journey(tmp_path, monkeypatch, acquired, cl=18, owner_hp=None, foe_talents=()):
    doc = acquired(cl)
    if owner_hp is not None:
        doc['ability_scores_and_statistics']['hit_points']['maximum'] = owner_hp
    foe = sheet(['FIRE_TAL_FIREBALL_ART', *foe_talents], cl=cl, dc=50, name='Hostile fire cultivator')
    foe['ability_scores_and_statistics']['hit_points']['maximum'] = 1000
    documents = {'worker2-owner': doc, 'worker2-foe': foe}
    monkeypatch.setattr(CombatService, '_factory_owner_sheet',
        lambda self, pid: deepcopy(documents[pid]))
    arena = {'stable_id': 'battlefield:maw-journey', 'display_name': 'Open field', 'width_squares': 12,
             'height_squares': 12, 'square_size_ft': 5, 'terrain_regions': [], 'starting_positions': {}}
    monkeypatch.setattr(CombatService, 'factory_arenas', lambda self: {'field': arena})
    def cold():
        return CombatService(ROOT, tmp_path)
    state = cold().create_journey(project_ids=list(documents), arena_id='field',
        positions={OWNER: {'x': 3, 'y': 6}, FOE: {'x': 4, 'y': 6}}, base_paces={OWNER: 5, FOE: 5})
    return cold, state['journey_id']


def test_native_world_owner_farming_admission_blocks_only_its_source(tmp_path, monkeypatch, acquired):
    from combat.fact_consent_admission import read
    cold, jid = journey(tmp_path, monkeypatch, acquired, cl=6)
    initial = cold().journey_state(jid)
    declaration = {'source': SOURCE, 'subject': FOE, 'kind': 'resource_farming',
        'scope': initial.get('scene_id', jid), 'value': 1, 'expires_at': 60, 'readers': []}
    with pytest.raises(ValueError, match='table-owner'):
        cold().journey_act(jid, initial['revision'], FOE, 'declare_fact', declaration)
    assert cold().journey_state(jid) == initial
    state = cold().journey_world_fact(jid, initial['revision'], declaration)
    assert cold().journey_state(jid) == state
    assert read(cold().journeys.load(jid), SOURCE, FOE, 'resource_farming', declaration['scope'], OWNER) is None
    result = cold().journey_start_combat(jid, state['revision'], {OWNER: 'team:a', FOE: 'team:b'})
    mid = result['match_id']
    combat = cold()
    prompts = burn(combat, TabletopService(combat, tmp_path), mid)
    engine = reload(tmp_path, mid)
    assert any(e.event_type == 'DAMAGE_COMMITTED' and e.actor_id == FOE and OWNER in e.target_ids
               and e.payload['hp_damage'] > 0 for e in engine.events)
    assert engine.state.actors[OWNER].resources[ESSENCE] == 0
    assert engine.state.actors[OWNER].resources['resource:core.stamina'] == 100
    assert not any(p['context']['reaction_source_id'].startswith(SOURCE) for p in prompts)


def test_native_minute_and_explicit_scene_limit_are_independent_of_rest(tmp_path, monkeypatch, acquired):
    cold, jid = journey(tmp_path, monkeypatch, acquired)
    initial = cold().journey_state(jid)
    state = cold().journey_act(jid, initial['revision'], OWNER, 'maw_devour', {})
    assert state['actors'][OWNER]['resources']['resource:core.stamina'] == 92
    assert state['actors'][OWNER]['source_states'][SOURCE]['used'] == 1
    assert cold().journey_state(jid) == state
    state = cold().journey_act(jid, state['revision'], OWNER, 'wait', {'seconds': 60})
    assert state['actors'][OWNER]['source_states'][SOURCE]['mode_until_num'] == 0
    assert state['actors'][OWNER]['source_states'][SOURCE]['used'] == 1
    assert not any(o['id'] == 'maw_devour' for o in cold().journey_menu(jid, OWNER)['options'])
    state = cold().journey_end_scene(jid, state['revision'], 'The encounter and its immediate danger are over.')
    assert state['events'][-1]['kind'] == 'SCENE_ENDED'
    assert state['events'][-1]['declaration_receipt']
    assert state['actors'][OWNER]['source_states'][SOURCE]['used'] == 0
    assert state['actors'][OWNER]['resources']['resource:core.stamina'] == 92
    assert any(o['id'] == 'maw_devour' for o in cold().journey_menu(jid, OWNER)['options'])
    assert cold().journey_state(jid) == state


def test_retained_overflow_survives_minute_expiry_and_next_native_fight(tmp_path, monkeypatch, acquired):
    cold, jid = journey(tmp_path, monkeypatch, acquired)
    state = cold().journey_state(jid)
    state = cold().journey_act(jid, state['revision'], OWNER, 'maw_devour', {})
    result = cold().journey_start_combat(jid, state['revision'], {OWNER: 'team:a', FOE: 'team:b'}, maximum_rounds=5)
    mid = result['match_id']
    combat = cold()
    table = TabletopService(combat, tmp_path)
    for _ in range(3):
        burn(combat, table, mid)
    assert reload(tmp_path, mid).state.actors[OWNER].resources[ESSENCE] == 6
    for _ in range(12):
        if reload(tmp_path, mid).state.terminal_result is not None:
            break
        settle(table, mid, table.state(mid)['menu']['end_turn'])
    state = cold().journey_resume(jid, cold().journey_state(jid)['revision'])
    state = cold().journey_act(jid, state['revision'], OWNER, 'wait', {'seconds': 61})
    assert len(state['actors'][OWNER]['source_states'][SOURCE]['records']) == 6
    result = cold().journey_start_combat(jid, state['revision'], {OWNER: 'team:a', FOE: 'team:b'})
    mid = result['match_id']
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    assert owner.resources[ESSENCE] == 6 and owner.resource_maximums[ESSENCE] < 6
    burn(cold(), TabletopService(cold(), tmp_path), mid)
    assert reload(tmp_path, mid).state.actors[OWNER].resources[ESSENCE] == 6


def test_native_fight_records_survive_combat_end_then_backlash_at_real_scene_end(tmp_path, monkeypatch, acquired):
    cold, jid = journey(tmp_path, monkeypatch, acquired, cl=6)
    state = cold().journey_state(jid)
    state = cold().journey_start_combat(jid, state['revision'], {OWNER: 'team:a', FOE: 'team:b'}, maximum_rounds=1)
    mid = state['match_id']
    combat = cold()
    table = TabletopService(combat, tmp_path)
    burn(combat, table, mid)
    for _ in range(4):
        engine = reload(tmp_path, mid)
        if engine.state.terminal_result is not None:
            break
        settle(table, mid, table.state(mid)['menu']['end_turn'])
    assert reload(tmp_path, mid).state.terminal_result is not None
    state = cold().journey_resume(jid, cold().journey_state(jid)['revision'], effect_resolutions={
        OWNER: 'The encounter and its timed effects are over.',
        FOE: 'The encounter and its timed effects are over.'})
    actor = state['actors'][OWNER]
    assert len(actor['source_states'][SOURCE]['records']) == 1
    assert actor['resources'][ESSENCE] == 1
    assert not any(e['kind'] == 'UNAVOIDABLE_DAMAGE_COMMITTED' for e in state['events'])
    before = actor['encounter_snapshot']['current_hp']
    state = cold().journey_end_scene(jid, state['revision'], 'The GM ends this meaningful scene.')
    actor = state['actors'][OWNER]
    assert actor['source_states'][SOURCE]['records'] == []
    assert actor['resources'][ESSENCE] == 0
    assert 1 <= before - actor['encounter_snapshot']['current_hp'] <= 6
    event = next(e for e in state['events'] if e['kind'] == 'UNAVOIDABLE_DAMAGE_COMMITTED')
    roller = DeterministicRollAuthority(jid + ':' + SOURCE + ':' + OWNER, counter=event['roll']['counter_start'])
    replay = roller.roll(DiceSpec(count=1, sides=6), actor_id=OWNER, reason='Undigested Calamity')
    assert replay.model_dump(mode='json', exclude_none=True) == event['roll']
    assert cold().journey_state(jid) == state


def test_backlash_reaches_native_zero_hp_state_without_temporary_hp_buffer(tmp_path, monkeypatch, acquired):
    # The owner keeps its 1 Hit Point: Devour Heaven and Earth gains one Essence from the foe's
    # real CP spend (the printed once-per-round generator). The foe's activation is its own
    # printed Fire-Sovereign Incarnation, a self-only Bonus Action, so no damage reaches the
    # owner and no Temporary HP is granted by this fight.
    cold, jid = journey(tmp_path, monkeypatch, acquired, cl=18, owner_hp=1,
                        foe_talents=['tianxia.talent.fire.fire_sovereign_incarnation'])
    state = cold().journey_state(jid)
    result = cold().journey_start_combat(jid, state['revision'], {OWNER: 'team:a', FOE: 'team:b'}, maximum_rounds=1)
    mid = result['match_id']
    combat = cold()
    table = TabletopService(combat, tmp_path)
    from tests.test_mgr_maw_native import play
    turn(table, mid, OWNER)
    play(combat, table, mid, 'Devour Heaven and Earth')
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    turn(table, mid, FOE)
    play(combat, table, mid, 'Sovereign Incarnation')
    for _ in range(4):
        if reload(tmp_path, mid).state.terminal_result is not None:
            break
        settle(table, mid, table.state(mid)['menu']['end_turn'])
    state = cold().journey_resume(jid, cold().journey_state(jid)['revision'], effect_resolutions={
        OWNER: 'The encounter and its timed effects are over.',
        FOE: 'The encounter and its timed effects are over.'})
    assert len(state['actors'][OWNER]['source_states'][SOURCE]['records']) == 1
    state = cold().journey_end_scene(jid, state['revision'], 'The GM ends the scene after the harmful activation.')
    actor = state['actors'][OWNER]
    assert actor['encounter_snapshot']['current_hp'] == 0
    assert actor['incapacitated'] == 1 and actor['resources'][ESSENCE] == 0
    assert actor['source_states'][SOURCE]['records'] == []
    assert cold().journey_state(jid) == state


class _Session:
    """Minimal journey session for calamity(): the state dict plus event recording."""
    def __init__(self, actor):
        self.state = {'journey_id': 'journey:maw-massive', 'actors': {'owner': actor}, 'events': []}
    def emit(self, kind, actor_id, **kw):
        self.state['events'].append(kind)


def _backlash_actor(maximum_hp, extra_rows):
    rows = [{'block': 'path_rider', 'kind': 'devouring_maw', 'role': 'devour'}, *extra_rows]
    return {'name': 'Owner', 'bundle': {'actor_template': {'maximum_hp': maximum_hp, 'resources': []},
                                        'typed_passives': rows},
            'resources': {ESSENCE: 1}, 'incapacitated': 0,
            'source_states': {SOURCE: {'records': [{'x': 1}], 'mode_until_num': 0, 'mode_until_den': 1,
                                       'mode_cl': 0, 'used': 0, 'roll_counter': 0}}}


@pytest.mark.parametrize('extra_rows, dies', [([], True),
    ([{'block': 'life_state', 'kind': 'death_mode', 'mode': 'ADVANTAGE', 'massive_multiplier': 3}], False)])
def test_backlash_massive_damage_uses_owners_death_rules(monkeypatch, extra_rows, dies):
    """Finding 4: journey backlash applies the owner's massive_multiplier, as combat does.

    A forced roll of 3 against a creature at 1 HP is 2 over its remaining HP: massive (threshold 2 =
    its maximum) for an ordinary creature, so it dies; Deathless's threshold is three times the maximum (6),
    so it does not. Without the shared rule both would die.
    """
    from types import SimpleNamespace
    from combat.gate2_rolls import DeterministicRollAuthority
    from combat.ext.devouring_maw_journey import calamity
    from combat.ext.life_state import DEAD
    monkeypatch.setattr(DeterministicRollAuthority, 'roll',
        lambda self, spec, **kw: SimpleNamespace(total=3, model_dump=lambda **k: {'total': 3}))
    actor = _backlash_actor(2, extra_rows)
    actor['encounter_snapshot'] = {'current_hp': 1, 'maximum_hp': 2, 'temporary_hp': 0, 'active': 1,
                                   'life_state': '', 'conditions': {}, 'death_saves': {'ok': 0, 'bad': 0}}
    session = _Session(actor)
    calamity(session, 'owner')
    snapshot = session.state['actors']['owner']['encounter_snapshot']
    dead = any(DEAD in str(c) for c in snapshot['conditions'].values())
    assert dead is dies
    assert snapshot['active'] == (0 if dies else 1)

